"""Programaciones de ETL, almacén y exportaciones por la API de admin, y el mapa de zonas
(docs/04 §11.4 y §11.5). Postgres real."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest
from etl.comun import almacen as alm
from etl.eventos_exportar import exportar

from app.config import get_settings
from app.db import create_pool
from app.services import programaciones
from tests.conftest import make_token
from tests.db import hacer_admin, sql

TIPO = "test.programacion"
U = timezone.utc


@pytest.fixture(autouse=True)
def _limpiar():
    def todo():
        sql("delete from etl_programaciones where parametros->>'tipo' = $1", TIPO)
        sql("delete from etl_ejecuciones where parametros->>'tipo' = $1", TIPO)
        sql("delete from eventos where tipo like 'test.programacion%'")
        sql("delete from eventos_exportaciones where tipo like 'test.programacion%'")

    todo()
    yield
    todo()
    sql("delete from precios where created_at >= '2024-04-01' and created_at < '2024-05-01'")
    sql("delete from locales where nombre like 'prog-%'")
    sql("delete from usuarios where alias like 'prog-%'")


@pytest.fixture
def admin(client):
    h = {"Authorization": f"Bearer {make_token()}"}
    hacer_admin(client.get("/v1/me", headers=h).json()["id"])
    return h


def _consulta(query: str, *args):
    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            return await conn.fetch(query, *args)
        finally:
            await conn.close()

    return asyncio.run(run())


def _vuelta(ahora=None) -> int:
    async def run():
        pool = await create_pool()
        try:
            return await programaciones.vuelta(pool, ahora)
        finally:
            await pool.close()

    return asyncio.run(run())


def _crear(client, admin, **extra):
    cuerpo = {
        "etl": "eventos_exportar",
        "cron": "0 6 * * *",
        "parametros": {"tipo": TIPO, "borrar": True},
        **extra,
    }
    return client.post("/v1/admin/etl/programaciones", headers=admin, json=cuerpo)


# ------------------------------------------------------------------ permisos
def test_solo_admin_programa(client, auth):
    assert client.get("/v1/admin/etl/programaciones", headers=auth).status_code == 403
    assert client.post("/v1/admin/almacen/probar", headers=auth).status_code == 403
    assert client.get("/v1/admin/eventos/exportaciones", headers=auth).status_code == 403
    assert client.get("/v1/admin/dashboard/zonas", headers=auth).status_code == 403


# ---------------------------------------------------------------- el CRUD
def test_crear_cambiar_y_borrar(client, admin):
    r = _crear(client, admin)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["activa"] is False and p["titulo"] and p["ultima_corrida"] is None
    prox = datetime.fromisoformat(p["proxima_corrida"].replace("Z", "+00:00"))
    assert (prox.hour, prox.minute) == (6, 0)  # el cron es UTC

    r = client.patch(
        f"/v1/admin/etl/programaciones/{p['id']}",
        headers=admin,
        json={"activa": True, "cron": "30 3 * * *"},
    )
    assert r.status_code == 200 and r.json()["activa"] is True
    assert r.json()["cron"] == "30 3 * * *"
    assert [x["id"] for x in client.get("/v1/admin/etl/programaciones", headers=admin).json()
            if x["parametros"].get("tipo") == TIPO] == [p["id"]]  # fmt: skip

    assert (
        client.delete(f"/v1/admin/etl/programaciones/{p['id']}", headers=admin).status_code == 204
    )
    assert (
        client.delete(f"/v1/admin/etl/programaciones/{p['id']}", headers=admin).status_code == 404
    )


def test_validaciones(client, admin):
    r = _crear(client, admin, cron="no es un cron")
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "cron_invalido"
    assert _crear(client, admin, etl="no_existe").status_code == 404
    r = _crear(client, admin, parametros={"inventado": 1})
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "etl_parametro_invalido"
    # un ETL que necesita subir un archivo no se puede programar
    r = _crear(client, admin, etl="locales_importar", parametros={})
    assert r.status_code == 422
    # el umbral solo existe para los eventos
    r = _crear(client, admin, etl="locales_exportar", parametros={}, al_superar_umbral=True)
    assert r.status_code == 422


def test_las_acciones_quedan_en_la_auditoria(client, admin):
    p = _crear(client, admin).json()
    client.delete(f"/v1/admin/etl/programaciones/{p['id']}", headers=admin)
    acciones = {
        r["accion"]
        for r in _consulta("select accion from auditoria_admin where entidad_id = $1", p["id"])
    }
    assert acciones == {"programacion.crear", "programacion.borrar"}


# -------------------------------------------------------------- el ciclo
def _fila(id_):
    return _consulta("select * from etl_programaciones where id = $1::uuid", id_)[0]


def test_la_vuelta_encola_lo_que_toca_y_reprograma(client, admin):
    p = _crear(client, admin, activa=True).json()
    ahora = datetime.now(U)
    assert _vuelta(ahora) == 0  # todavía no es la hora
    _vuelta_en = datetime.fromisoformat(p["proxima_corrida"].replace("Z", "+00:00"))
    assert _vuelta(_vuelta_en) == 1  # llegó la hora

    f = _fila(p["id"])
    assert f["ultima_ejecucion_id"] is not None
    assert f["proxima_corrida"] > _vuelta_en  # reprogramada para el día siguiente
    ej = _consulta("select * from etl_ejecuciones where id = $1", f["ultima_ejecucion_id"])[0]
    assert (ej["etl"], ej["ejecutor"], ej["creado_por"]) == ("eventos_exportar", "web", None)
    assert json.loads(ej["parametros"]) == {"tipo": TIPO, "borrar": True}
    aud = _consulta(
        "select usuario_id from auditoria_admin where accion = 'programacion.ejecutar' "
        "and entidad_id = $1",
        str(ej["id"]),
    )
    assert len(aud) == 1 and aud[0]["usuario_id"] is None  # lo hizo el sistema


def test_una_programacion_pausada_no_corre(client, admin):
    p = _crear(client, admin).json()  # activa = false
    assert _vuelta(datetime.fromisoformat(p["proxima_corrida"].replace("Z", "+00:00"))) == 0


def test_no_apila_si_la_anterior_sigue_en_cola(client, admin):
    p = _crear(client, admin, activa=True).json()
    t1 = datetime.fromisoformat(p["proxima_corrida"].replace("Z", "+00:00"))
    assert _vuelta(t1) == 1
    # la ejecución quedó `en_cola` (nadie la tomó): el día siguiente NO se encola otra
    assert _vuelta(t1 + timedelta(days=1)) == 0
    n = _consulta("select count(*) as n from etl_ejecuciones where parametros->>'tipo' = $1", TIPO)
    assert n[0]["n"] <= 1  # (si el ejecutor web ya la tomó y terminó, no hay duplicados igual)


def test_con_dos_vueltas_a_la_vez_corre_una_sola(client, admin):
    """El lock de Postgres: dos réplicas pasando por la misma programación no la duplican."""
    p = _crear(client, admin, activa=True).json()
    t1 = datetime.fromisoformat(p["proxima_corrida"].replace("Z", "+00:00"))

    async def run():
        pool = await create_pool()
        try:
            return await asyncio.gather(
                programaciones.vuelta(pool, t1), programaciones.vuelta(pool, t1)
            )
        finally:
            await pool.close()

    assert sum(asyncio.run(run())) == 1


def test_el_umbral_de_eventos_encola_el_export(client, admin, config_temporal):
    p = _crear(client, admin, activa=True, al_superar_umbral=True).json()
    sql("insert into eventos (tipo, datos) values ($1, '{}'::jsonb)", TIPO)
    config_temporal("eventos_max_filas", "1000000000")
    ahora = datetime.now(U)
    assert _vuelta(ahora) == 0  # no se superó el tope
    config_temporal("eventos_max_filas", "0")
    assert _vuelta(ahora) == 1  # se superó: encola aunque el cron no toque
    assert _fila(p["id"])["ultima_corrida"] is not None
    assert _vuelta(ahora + timedelta(minutes=5)) == 0  # y no insiste antes de una hora


# ------------------------------------------------- el almacén por la API
def test_probar_almacen_en_disco(client, admin, monkeypatch, tmp_path):
    monkeypatch.delenv("EXPORT_S3_ENDPOINT", raising=False)
    monkeypatch.setenv("ETL_EXPORT_DIR", str(tmp_path))
    r = client.post("/v1/admin/almacen/probar", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["almacen"] == "disco"


def test_probar_almacen_que_falla_da_502_con_explicacion(client, admin, monkeypatch):
    monkeypatch.setenv("EXPORT_S3_ENDPOINT", "http://127.0.0.1:9")  # nadie escucha
    monkeypatch.setenv("EXPORT_S3_BUCKET", "x")
    monkeypatch.setenv("EXPORT_S3_KEY", "k")
    monkeypatch.setenv("EXPORT_S3_SECRET", "s")
    r = client.post("/v1/admin/almacen/probar", headers=admin)
    assert r.status_code == 502
    d = r.json()["detail"]
    assert d["codigo"] == "almacen_fallo" and d["como_resolver"]


def test_exportaciones_se_listan_y_se_descargan(client, admin, monkeypatch, tmp_path):
    monkeypatch.delenv("EXPORT_S3_ENDPOINT", raising=False)
    monkeypatch.setenv("ETL_EXPORT_DIR", str(tmp_path))
    for i in range(3):
        sql("insert into eventos (tipo, datos) values ($1, $2::jsonb)", TIPO, json.dumps({"i": i}))

    class Ctx:
        ejecucion_id = None
        filas = None

        def log(self, t):
            pass

    asyncio.run(exportar({"tipo": TIPO, "borrar": True}, Ctx(), alm.AlmacenDisco(tmp_path)))
    lista = [
        e for e in client.get("/v1/admin/eventos/exportaciones", headers=admin).json()
        if e["tipo"] == TIPO
    ]  # fmt: skip
    assert len(lista) == 1 and (lista[0]["filas"], lista[0]["borradas"]) == (3, 3)
    r = client.get(f"/v1/admin/eventos/exportaciones/{lista[0]['id']}/descargar", headers=admin)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert alm.sha256(r.content) == lista[0]["sha256"] == r.headers["x-sha256"]
    assert client.get(
        f"/v1/admin/eventos/exportaciones/{uuid.uuid4()}/descargar", headers=admin
    ).status_code == 404  # fmt: skip


# --------------------------------------------------------- resumen y mapa
def test_el_resumen_avisa_cuando_se_pasa_el_tope_de_eventos(client, admin, config_temporal):
    sql("insert into eventos (tipo, datos) values ($1, '{}'::jsonb)", TIPO)
    config_temporal("eventos_max_filas", "1000000000")
    ev = client.get("/v1/admin/dashboard/resumen", headers=admin).json()["eventos"]
    assert ev["superado"] is False and ev["total"] >= 1
    config_temporal("eventos_max_filas", "0")
    ev = client.get("/v1/admin/dashboard/resumen", headers=admin).json()["eventos"]
    assert ev["superado"] is True and ev["max_filas"] == 0


def _zona_con_precios(lat: float, lng: float, n: int, locales: int = 1) -> None:
    uid = str(uuid.uuid4())
    sql(
        "insert into usuarios (id, auth_id, alias) values ($1::uuid, $2::uuid, $3)",
        uid, str(uuid.uuid4()), f"prog-{uid[:6]}",
    )  # fmt: skip
    for k in range(locales):
        lid = str(uuid.uuid4())
        sql(
            "insert into locales (id, nombre, ubicacion) values ($1::uuid, $2, "
            "st_setsrid(st_makepoint($3, $4), 4326)::geography)",
            lid, f"prog-{lid[:6]}", lng + k * 0.00001, lat,
        )  # fmt: skip
        for _ in range(n):
            sql(
                "insert into precios (producto_canonico_id, local_id, precio, user_id, fecha, "
                "created_at) values ((select id from productos_canonicos limit 1), $1::uuid, 10, "
                "$2::uuid, '2024-04-10T12:00:00Z'::timestamptz, "
                "'2024-04-10T12:00:00Z'::timestamptz)",
                lid, uid,
            )  # fmt: skip


def _zonas(client, admin):
    r = client.get(
        "/v1/admin/dashboard/zonas",
        headers=admin,
        params={"desde": "2024-04-01T00:00:00Z", "hasta": "2024-05-01T00:00:00Z"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_zonas_devuelve_geojson_de_celdas_con_el_minimo(client, admin, config_temporal):
    config_temporal("dashboard_celda_min_precios", "5")
    _zona_con_precios(-34.60, -58.40, 4, locales=2)  # 8 precios en 2 locales de la misma celda
    _zona_con_precios(-31.40, -64.19, 3)  # 3 precios: por debajo del mínimo
    z = _zonas(client, admin)
    assert z["type"] == "FeatureCollection" and z["min_precios"] == 5
    assert len(z["features"]) == 1  # la celda de 3 precios no se dibuja (privacidad)
    f = z["features"][0]
    assert f["properties"]["precios"] == 8 and f["properties"]["locales"] == 2
    assert 1 <= f["properties"]["nivel"] <= 5
    anillo = f["geometry"]["coordinates"][0]
    assert f["geometry"]["type"] == "Polygon" and anillo[0] == anillo[-1]
    xs = [c[0] for c in anillo]
    assert min(xs) < -58.40 < max(xs)  # la celda contiene el punto


def test_zonas_respeta_el_minimo_y_el_tamano_de_celda(client, admin, config_temporal):
    _zona_con_precios(-34.60, -58.40, 3)
    config_temporal("dashboard_celda_min_precios", "4")
    assert _zonas(client, admin)["features"] == []
    config_temporal("dashboard_celda_min_precios", "3")
    config_temporal("dashboard_celda_m", "1000")
    a = _zonas(client, admin)["features"][0]["geometry"]["coordinates"][0]
    config_temporal("dashboard_celda_m", "250")
    b = _zonas(client, admin)["features"][0]["geometry"]["coordinates"][0]
    ancho = lambda c: max(x for x, _ in c) - min(x for x, _ in c)  # noqa: E731
    assert ancho(a) == pytest.approx(ancho(b) * 4, rel=0.01)  # 1000 m = 4 celdas de 250 m


def test_zonas_celdas_casi_cuadradas(client, admin, config_temporal):
    """A -35° un grado de longitud mide ~20 % menos que uno de latitud: el ancho se corrige."""
    config_temporal("dashboard_celda_min_precios", "1")
    config_temporal("dashboard_celda_m", "1000")
    _zona_con_precios(-34.60, -58.40, 1)
    c = _zonas(client, admin)["features"][0]["geometry"]["coordinates"][0]
    ancho_m = (max(x for x, _ in c) - min(x for x, _ in c)) * 111320 * 0.8221  # cos(34.6°)
    alto_m = (max(y for _, y in c) - min(y for _, y in c)) * 111320
    assert ancho_m == pytest.approx(1000, rel=0.03) and alto_m == pytest.approx(1000, rel=0.03)


def test_zonas_sin_precios_en_el_periodo(client, admin):
    r = client.get(
        "/v1/admin/dashboard/zonas",
        headers=admin,
        params={"desde": "2001-01-01T00:00:00Z", "hasta": "2001-01-02T00:00:00Z"},
    )
    assert r.status_code == 200 and r.json()["features"] == []
