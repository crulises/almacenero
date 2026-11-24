"""ETL desde el panel (docs/04 §10-A): definiciones, subida de archivos, cola, cancelación,
auditoría y permisos. Postgres real; el ejecutor `web` corre de verdad (subproceso)."""

import asyncio
import hashlib
import time

import asyncpg
import pytest

from app.config import get_settings
from tests.conftest import make_token
from tests.db import hacer_admin, hacer_rol, sql

H_CSV = "# formato: catalogo_curado_v1\nean,nombre,marca\n"


@pytest.fixture(autouse=True)
def _limpiar():
    def borrar():
        sql("update catalogo_lotes set etl_ejecucion_id = null where nombre_archivo like 't-etl%'")
        sql("delete from catalogo_lotes where nombre_archivo like 't-etl%'")
        sql(
            "delete from etl_ejecuciones where creado_por in"
            " (select id from usuarios where alias like 'etl-t-%') or etl = 'inexistente'"
        )
        sql("delete from etl_archivos where nombre like 't-etl%'")
        sql("delete from productos_canonicos where ean like '79999%'")
        sql("delete from producto_fuentes where ean like '79999%'")

    borrar()
    yield
    borrar()


@pytest.fixture
def admin(client):
    h = {"Authorization": f"Bearer {make_token()}"}
    yo = client.get("/v1/me", headers=h).json()
    hacer_admin(yo["id"])
    sql("update usuarios set alias = $2 where id = $1::uuid", yo["id"], "etl-t-" + yo["id"][:8])
    return h


def _fila(consulta, *args):
    async def run():
        c = await asyncpg.connect(get_settings().database_url)
        try:
            return await c.fetchrow(consulta, *args)
        finally:
            await c.close()

    return asyncio.run(run())


def subir(client, h, nombre="t-etl.csv", contenido=b"hola"):
    return client.post(
        "/v1/admin/etl/archivos",
        params={"nombre": nombre},
        content=contenido,
        headers={**h, "Content-Type": "application/octet-stream"},
    )


def esperar(client, h, id_, hasta=("ok", "fallo", "cancelada"), s=60):
    t0 = time.time()
    while time.time() - t0 < s:
        e = client.get(f"/v1/admin/etl/ejecuciones/{id_}", headers=h).json()
        if e["estado"] in hasta:
            return e
        time.sleep(0.4)
    raise AssertionError(f"no terminó: {e}")


def test_solo_el_admin_ve_y_dispara_etl(client, auth):
    assert client.get("/v1/admin/etl", headers=auth).status_code == 403
    uid = client.get("/v1/me", headers=auth).json()["id"]
    hacer_rol(uid, "moderador")
    assert client.get("/v1/admin/etl", headers=auth).status_code == 403
    assert (
        client.post("/v1/admin/etl/catalogo_calidad/ejecutar", json={}, headers=auth).status_code
        == 403
    )
    assert client.get("/v1/admin/etl/ejecuciones", headers=auth).status_code == 403


def test_las_definiciones_traen_lo_que_el_panel_necesita(client, admin):
    r = client.get("/v1/admin/etl", headers=admin)
    assert r.status_code == 200
    por_clave = {d["clave"]: d for d in r.json()}
    assert (
        por_clave["sepa"]["ejecutor"] == "local"
        and por_clave["curado_importar"]["ejecutor"] == "web"
    )
    p = por_clave["curado_importar"]["parametros"][0]
    assert (p["nombre"], p["tipo"], p["obligatorio"]) == ("archivo", "archivo", True) and p["ayuda"]
    assert "ejecutar" not in por_clave["sepa"]


def test_subir_un_archivo_lo_guarda_con_su_hash_y_audita(client, admin):
    r = subir(client, admin, contenido=b"contenido")
    assert r.status_code == 201
    d = r.json()
    assert d["sha256"] == hashlib.sha256(b"contenido").hexdigest() and d["tamano"] == 9
    assert d["nombre"] == "t-etl.csv"
    aud = client.get("/v1/admin/auditoria", params={"entidad": "etl"}, headers=admin).json()
    assert any(a["accion"] == "etl.archivo_subir" for a in aud["items"])


def test_archivo_vacio_o_demasiado_grande_explica_la_regla(client, admin):
    r = subir(client, admin, contenido=b"")
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "etl_archivo_vacio"
    r = subir(client, admin, contenido=b"x" * (25 * 1024 * 1024 + 1))
    assert r.status_code == 413 and r.json()["detail"]["codigo"] == "etl_archivo_grande"
    assert "25" in r.json()["detail"]["mensaje"]


def test_parametros_invalidos_dicen_cual_y_por_que(client, admin):
    r = client.post(
        "/v1/admin/etl/catalogo_calidad/ejecutar",
        json={"parametros": {"muestra": "x"}},
        headers=admin,
    )
    d = r.json()["detail"]
    assert (
        r.status_code == 422
        and d["codigo"] == "etl_parametro_invalido"
        and d["parametro"] == "muestra"
    )
    r = client.post(
        "/v1/admin/etl/curado_importar/ejecutar", json={"parametros": {}}, headers=admin
    )
    assert r.json()["detail"]["parametro"] == "archivo"
    r = client.post(
        "/v1/admin/etl/curado_importar/ejecutar",
        json={"parametros": {"archivo": "00000000-0000-0000-0000-000000000000"}},
        headers=admin,
    )
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "etl_archivo_inexistente"
    assert (
        client.post("/v1/admin/etl/inexistente/ejecutar", json={}, headers=admin).status_code == 404
    )


def test_un_etl_liviano_corre_en_el_backend_y_deja_todo_registrado(client, admin):
    r = client.post(
        "/v1/admin/etl/catalogo_calidad/ejecutar",
        json={"parametros": {"muestra": 2}},
        headers=admin,
    )
    assert r.status_code == 201
    e = r.json()
    assert e["estado"] == "en_cola" and e["ejecutor"] == "web" and e["etl"] == "catalogo_calidad"
    fin = esperar(client, admin, e["id"])
    assert fin["estado"] == "ok", fin["log"]
    assert fin["terminado_en"] and "Productos" in fin["log"] or fin["log"]
    lista = client.get("/v1/admin/etl/ejecuciones", headers=admin).json()
    assert any(x["id"] == e["id"] for x in lista["items"]) and "log" not in lista["items"][0]
    aud = client.get(
        "/v1/admin/auditoria", params={"entidad": "etl", "entidad_id": e["id"]}, headers=admin
    ).json()
    assert [a["accion"] for a in aud["items"]] == ["etl.iniciar"]


def test_importar_csv_curado_desde_el_panel_en_seco_y_despues_de_verdad(client, admin):
    csv = (
        b"# formato: catalogo_curado_v1\n"
        b"ean,nombre,marca,tamano_valor,tamano_unidad\n"
        b"7999900000018,Aceite Girasol,Cocinero,900,ml\n"
        b"123,EAN corto,,,\n"
    )
    a = subir(client, admin, "t-etl-curado.csv", csv).json()
    seco = client.post(
        "/v1/admin/etl/curado_importar/ejecutar",
        json={"parametros": {"archivo": a["id"]}},
        headers=admin,
    ).json()
    fin = esperar(client, admin, seco["id"])
    assert fin["estado"] == "ok", fin["log"]
    assert fin["reporte"]["nuevos"] == 1 and fin["reporte"]["invalidas"] == {
        "ean_largo_invalido": 1
    }
    assert fin["filas"] == 2 and "SIMULACRO" in fin["log"]
    # en seco no escribió nada ni borró el archivo
    assert (
        _fila("select count(*) as n from productos_canonicos where ean = '7999900000018'")["n"] == 0
    )
    assert _fila("select count(*) as n from etl_archivos where id = $1::uuid", a["id"])["n"] == 1
    real = client.post(
        "/v1/admin/etl/curado_importar/ejecutar",
        json={"parametros": {"archivo": a["id"], "aplicar": True}},
        headers=admin,
    ).json()
    fin = esperar(client, admin, real["id"])
    assert fin["estado"] == "ok", fin["log"]
    assert fin["reporte"]["lote_id"]
    # el archivo se borró y el lote quedó atado a la ejecución y a quien la pidió
    ya = client.post(
        "/v1/admin/etl/curado_importar/ejecutar",
        json={"parametros": {"archivo": a["id"]}},
        headers=admin,
    )
    assert ya.status_code == 422 and ya.json()["detail"]["codigo"] == "etl_archivo_inexistente"
    me = client.get("/v1/me", headers=admin).json()["id"]
    lote = _fila("select * from catalogo_lotes where etl_ejecucion_id = $1::uuid", real["id"])
    assert lote is not None and str(lote["subido_por"]) == me
    assert (
        _fila("select count(*) as n from productos_canonicos where ean = '7999900000018'")["n"] == 1
    )


def test_cancelar_una_que_espera_en_cola_la_cancela_ya(client, admin):
    # `local`: nadie la toma en este test
    e = client.post(
        "/v1/admin/etl/sepa/ejecutar",
        json={"parametros": {"archivos": "no-existe.zip"}},
        headers=admin,
    ).json()
    assert e["ejecutor"] == "local" and e["estado"] == "en_cola"
    r = client.post(f"/v1/admin/etl/ejecuciones/{e['id']}/cancelar", headers=admin)
    assert r.status_code == 200 and r.json()["estado"] == "cancelada" and r.json()["terminado_en"]
    again = client.post(f"/v1/admin/etl/ejecuciones/{e['id']}/cancelar", headers=admin)
    assert again.status_code == 409 and again.json()["detail"]["codigo"] == "etl_ya_terminada"
    acciones = [
        a["accion"]
        for a in client.get(
            "/v1/admin/auditoria", params={"entidad_id": e["id"]}, headers=admin
        ).json()["items"]
    ]
    assert sorted(acciones) == ["etl.cancelar", "etl.iniciar"]


def test_cancelar_una_corriendo_pide_la_cancelacion(client, admin):
    e = client.post(
        "/v1/admin/etl/sepa/ejecutar", json={"parametros": {"archivos": "x.zip"}}, headers=admin
    ).json()
    sql(
        "update etl_ejecuciones set estado='corriendo', iniciado_en=now(), latido_en=now()"
        " where id=$1::uuid",
        e["id"],
    )
    r = client.post(f"/v1/admin/etl/ejecuciones/{e['id']}/cancelar", headers=admin)
    assert r.status_code == 200 and r.json()["estado"] == "corriendo"
    assert r.json()["cancelar"] is True


def test_una_ejecucion_que_no_existe_da_404(client, admin):
    r = client.get("/v1/admin/etl/ejecuciones/00000000-0000-0000-0000-000000000000", headers=admin)
    assert r.status_code == 404
