"""Dashboard de admin (docs/04 §11, corte 19a): tarjetas, series, rankings, estrellas y zona.
Contra Postgres real. Los datos de prueba viven en marzo de 2024 (la base de desarrollo no tiene
nada de esa fecha) y se borran al terminar."""

import asyncio
import uuid
from datetime import datetime, timezone

import asyncpg
import pytest

from app.config import get_settings
from app.services import dashboard
from tests.conftest import make_token
from tests.db import hacer_admin, sql

EAN = "7790070411112"  # del seed
ALIAS = "dash-"
DESDE = "2024-03-09T03:00:00Z"  # 00:00 del 9 de marzo en Buenos Aires
HASTA = "2024-03-11T03:00:00Z"  # 00:00 del 11 de marzo en Buenos Aires
UTC = timezone.utc


def _t(texto: str) -> datetime:
    """'2024-03-10T02:30:00Z' -> datetime con zona (asyncpg no convierte textos a timestamptz)."""
    return datetime.fromisoformat(texto.replace("Z", "+00:00"))


@pytest.fixture(autouse=True)
def _limpiar():
    """Cada test borra lo que creó (los datos de marzo de 2024 son solo de estos tests)."""
    yield
    sql("delete from precios where local_id in (select id from locales where nombre like 'dash-%')")
    sql(
        "delete from eventos where usuario_id in "
        "(select id from usuarios where alias like 'dash-%')"
    )
    sql(
        "delete from sugerencias_catalogo where usuario_id in "
        "(select id from usuarios where alias like 'dash-%')"
    )
    sql("delete from invitaciones_usos where usada_en >= '2024-03-01' and usada_en < '2024-04-01'")
    sql("delete from invitaciones where nota = 'dash-test'")
    sql("delete from locales where nombre like 'dash-%'")
    sql("delete from usuarios where alias like 'dash-%'")


@pytest.fixture
def admin(client):
    h = {"Authorization": f"Bearer {make_token()}"}
    hacer_admin(client.get("/v1/me", headers=h).json()["id"])
    return h


def _usuario(alias: str, anonimo: bool = True) -> str:
    uid = str(uuid.uuid4())
    sql(
        "insert into usuarios (id, auth_id, alias, es_anonimo) values ($1::uuid, $2::uuid, $3, $4)",
        uid,
        str(uuid.uuid4()),
        f"{ALIAS}{alias}",
        anonimo,
    )
    return uid


def _local() -> str:
    lid = str(uuid.uuid4())
    sql(
        "insert into locales (id, nombre, ubicacion) values ($1::uuid, $2, "
        "st_setsrid(st_makepoint(-35.0, -55.0), 4326)::geography)",
        lid,
        f"dash-{uuid.uuid4().hex[:8]}",
    )
    return lid


def _precio(uid: str, local: str, cuando: str) -> None:
    sql(
        """
        insert into precios (producto_canonico_id, local_id, precio, user_id, fecha, created_at)
        values ((select id from productos_canonicos where ean = $1), $2::uuid, 100, $3::uuid,
                $4::timestamptz, $4::timestamptz)
        """,
        EAN,
        local,
        uid,
        _t(cuando),
    )


@pytest.fixture
def cargas():
    """Tres precios alrededor de la medianoche argentina (UTC-3, sin horario de verano)."""
    uid = _usuario(uuid.uuid4().hex[:6])
    local = _local()
    _precio(uid, local, "2024-03-10T02:30:00Z")  # 23:30 del 9 en Buenos Aires
    _precio(uid, local, "2024-03-10T03:30:00Z")  # 00:30 del 10
    _precio(uid, local, "2024-03-10T12:00:00Z")  # 09:00 del 10
    return uid


def _serie(client, admin, **params):
    params = {"desde": DESDE, "hasta": HASTA, "granularidad": "dia", **params}
    return client.get("/v1/admin/dashboard/series", headers=admin, params=params)


# ----------------------------------------------------------------- permisos
@pytest.mark.parametrize("ruta", ["resumen", "series", "rankings", "estrellas"])
def test_solo_admin_ve_el_dashboard(client, auth, ruta):
    assert client.get(f"/v1/admin/dashboard/{ruta}", headers=auth).status_code == 403
    assert client.get(f"/v1/admin/dashboard/{ruta}").status_code in (401, 403)


# ------------------------------------------------------------- zona horaria
def test_la_medianoche_argentina_parte_el_dia(client, admin, cargas):
    r = _serie(client, admin, zona="America/Buenos_Aires")
    assert r.status_code == 200, r.text
    puntos = r.json()["puntos"]
    # El 9 argentino (23:30) tiene 1 precio; el 10 (00:30 y 09:00) tiene 2. Agrupar por día UTC
    # habría dado 1 y 2 en otros días (el 10 UTC contendría los tres, 02:30Z incluido).
    assert [(p["inicio_utc"], p["valor"]) for p in puntos] == [
        ("2024-03-09T03:00:00Z", 1),
        ("2024-03-10T03:00:00Z", 2),
    ]


def test_en_utc_los_mismos_datos_caen_en_otros_dias(client, admin, cargas):
    r = _serie(
        client, admin, zona="UTC", desde="2024-03-09T00:00:00Z", hasta="2024-03-11T00:00:00Z"
    )
    puntos = r.json()["puntos"]
    assert [(p["inicio_utc"], p["valor"]) for p in puntos] == [
        ("2024-03-09T00:00:00Z", 0),
        ("2024-03-10T00:00:00Z", 3),
    ]


def test_zona_por_defecto_es_la_del_config(client, admin, cargas):
    r = _serie(client, admin)
    assert r.json()["zona"] == "America/Buenos_Aires"
    assert r.json()["puntos"][0]["inicio_utc"] == "2024-03-09T03:00:00Z"


@pytest.mark.parametrize("sesion", ["UTC", "America/Buenos_Aires", "Asia/Tokyo"])
def test_el_resultado_no_depende_de_la_zona_de_la_sesion(cargas, sesion):
    """Regla 6b: con `timestamptz` el valor es un instante; la zona de la sesión no lo mueve."""

    async def run():
        conn = await asyncpg.connect(
            get_settings().database_url, server_settings={"timezone": sesion}
        )
        try:
            p = dashboard.periodo(
                datetime(2024, 3, 9, 3, tzinfo=UTC), datetime(2024, 3, 11, 3, tzinfo=UTC)
            )
            return await dashboard.serie(conn, "precios", "dia", p, "America/Buenos_Aires")
        finally:
            await conn.close()

    puntos = asyncio.run(run())
    assert [(p["inicio_utc"], p["valor"]) for p in puntos] == [
        (datetime(2024, 3, 9, 3, tzinfo=UTC), 1),
        (datetime(2024, 3, 10, 3, tzinfo=UTC), 2),
    ]


def test_otra_zona_mueve_los_buckets(client, admin, cargas):
    # Tokio (UTC+9): su día empieza a las 15:00 UTC del día anterior.
    r = _serie(
        client, admin, zona="Asia/Tokyo", desde="2024-03-09T15:00:00Z", hasta="2024-03-11T15:00:00Z"
    )
    # Los tres precios caen en el 10 de marzo de Tokio (15:00Z del 9 a 15:00Z del 10).
    assert [(p["inicio_utc"], p["valor"]) for p in r.json()["puntos"]] == [
        ("2024-03-09T15:00:00Z", 3),
        ("2024-03-10T15:00:00Z", 0),
    ]


def test_zona_invalida_da_422(client, admin):
    for zona in ("Mars/Olympus", "ART", ""):
        r = _serie(client, admin, zona=zona) if zona else _serie(client, admin, zona=" ")
        assert r.status_code == 422, zona
        assert r.json()["detail"]["codigo"] == "zona_invalida"
    # el resumen también la valida
    assert (
        client.get(
            "/v1/admin/dashboard/resumen", headers=admin, params={"zona": "Nada/Nada"}
        ).status_code
        == 422
    )


def test_la_zona_del_config_se_valida_al_editarla(client, admin):
    r = client.put(
        "/v1/admin/config/panel_zona_horaria", headers=admin, json={"valor": "Nada/Nada"}
    )
    assert r.status_code == 422
    r = client.put("/v1/admin/config/dashboard_activo_dias", headers=admin, json={"valor": 0})
    assert r.status_code == 422


def test_semana_arranca_el_lunes(client, admin, cargas):
    # 10/03/2024 es domingo: la semana ISO empezó el lunes 4 a las 00:00 argentinas (03:00 UTC).
    r = _serie(
        client,
        admin,
        granularidad="semana",
        desde="2024-03-04T03:00:00Z",
        hasta="2024-03-18T03:00:00Z",
    )
    puntos = r.json()["puntos"]
    assert puntos[0]["inicio_utc"] == "2024-03-04T03:00:00Z"
    assert puntos[0]["valor"] == 3
    assert puntos[1]["inicio_utc"] == "2024-03-11T03:00:00Z"


def test_hora_y_mes(client, admin, cargas):
    r = _serie(
        client,
        admin,
        granularidad="hora",
        desde="2024-03-10T02:00:00Z",
        hasta="2024-03-10T05:00:00Z",
    )
    assert [(p["inicio_utc"], p["valor"]) for p in r.json()["puntos"]] == [
        ("2024-03-10T02:00:00Z", 1),
        ("2024-03-10T03:00:00Z", 1),
        ("2024-03-10T04:00:00Z", 0),
    ]
    r = _serie(
        client,
        admin,
        granularidad="mes",
        desde="2024-03-01T03:00:00Z",
        hasta="2024-05-01T03:00:00Z",
    )
    puntos = r.json()["puntos"]
    assert [p["inicio_utc"] for p in puntos] == ["2024-03-01T03:00:00Z", "2024-04-01T03:00:00Z"]
    assert puntos[0]["valor"] == 3


def test_periodo_invalido(client, admin):
    r = _serie(client, admin, desde=HASTA, hasta=DESDE)
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "periodo_invalido"
    # un año por hora = 8760 barras
    r = _serie(
        client,
        admin,
        granularidad="hora",
        desde="2023-01-01T00:00:00Z",
        hasta="2024-01-01T00:00:00Z",
    )
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "periodo_invalido"
    assert _serie(client, admin, metrica="nada").status_code == 422


# ------------------------------------------------------------------ series
def test_validaciones_queda_en_cero(client, admin, cargas):
    puntos = _serie(client, admin, metrica="validaciones").json()["puntos"]
    assert [p["valor"] for p in puntos] == [0, 0]


def test_activos_separa_anonimos_y_registrados(client, admin):
    local = _local()
    anon, reg = _usuario("anon"), _usuario("reg", anonimo=False)
    for u in (anon, reg, reg):
        _precio(u, local, "2024-03-10T15:00:00Z")
    sql(
        "insert into sugerencias_catalogo (ean, usuario_id, cambios, created_at) "
        "values ($1, $2::uuid, '{\"nombre\": \"x\"}', '2024-03-10T16:00:00Z')",
        EAN,
        reg,
    )
    p = _serie(client, admin, metrica="activos").json()["puntos"]
    assert (p[1]["valor"], p[1]["anonimos"], p[1]["registrados"]) == (2, 1, 1)
    assert p[0]["valor"] == 0


def test_invitaciones_aceptadas_por_dia(client, admin):
    sql(
        "insert into invitaciones_usos (usada_en) values "
        "('2024-03-10T02:30:00Z'::timestamptz), ('2024-03-10T20:00:00Z'::timestamptz)"
    )
    p = _serie(client, admin, metrica="invitaciones").json()["puntos"]
    assert [x["valor"] for x in p] == [1, 1]


# ------------------------------------------------------------------ resumen
def test_resumen(client, admin, cargas, config_temporal):
    r = client.get(
        "/v1/admin/dashboard/resumen", headers=admin, params={"desde": DESDE, "hasta": HASTA}
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["precios"]["periodo"] == 3 and d["precios"]["total"] >= 3
    assert d["validaciones"] == {"periodo": 0, "total": d["validaciones"]["total"]}
    assert d["usuarios_activos"]["dias"] == 7
    assert d["zona"] == "America/Buenos_Aires"
    inv = d["invitaciones"]
    assert inv["emitidas"] == inv["disponibles"] + inv["usadas"] + inv["vencidas"]
    config_temporal("dashboard_activo_dias", "30")
    r = client.get("/v1/admin/dashboard/resumen", headers=admin)
    assert r.json()["usuarios_activos"]["dias"] == 30


def test_resumen_cuenta_invitaciones(client, admin):
    sql(
        "insert into invitaciones (codigo, usos_max, usos, nota, usada_at) values "
        "('dash-a', 1, 1, 'dash-test', now()), ('dash-b', 1, 0, 'dash-test', null), "
        "('dash-c', null, 0, 'dash-test', null)"
    )
    sql("update invitaciones set vence = now() - interval '1 day' where codigo = 'dash-c'")
    antes = client.get("/v1/admin/dashboard/resumen", headers=admin).json()["invitaciones"]
    assert antes["usadas"] >= 1 and antes["vencidas"] >= 1 and antes["disponibles"] >= 1
    sql("delete from invitaciones where nota = 'dash-test'")
    despues = client.get("/v1/admin/dashboard/resumen", headers=admin).json()["invitaciones"]
    assert despues["emitidas"] == antes["emitidas"] - 3
    assert despues["usadas"] == antes["usadas"] - 1
    assert despues["vencidas"] == antes["vencidas"] - 1
    assert despues["disponibles"] == antes["disponibles"] - 1


# ----------------------------------------------------------------- rankings
def test_ranking_de_precios_con_alias_y_sin_email(client, admin):
    local = _local()
    a, b = _usuario("rank-a"), _usuario("rank-b")
    for _ in range(3):
        _precio(a, local, "2024-03-10T12:00:00Z")
    _precio(b, local, "2024-03-10T12:00:00Z")
    r = client.get(
        "/v1/admin/dashboard/rankings",
        headers=admin,
        params={"tipo": "precios", "desde": DESDE, "hasta": HASTA},
    )
    assert r.status_code == 200, r.text
    items = r.json()
    assert [(i["alias"], i["cantidad"]) for i in items][:2] == [
        (f"{ALIAS}rank-a", 3),
        (f"{ALIAS}rank-b", 1),
    ]
    assert all("email" not in i for i in items)


def test_ranking_de_sugerencias_y_productos(client, admin):
    u = _usuario("rank-s")
    sql(
        "insert into sugerencias_catalogo (ean, usuario_id, cambios, created_at) "
        "values ($1, $2::uuid, '{\"nombre\": \"x\"}', '2024-03-10T16:00:00Z')",
        EAN,
        u,
    )
    r = client.get(
        "/v1/admin/dashboard/rankings",
        headers=admin,
        params={"tipo": "sugerencias", "desde": DESDE, "hasta": HASTA},
    )
    assert r.json()[0]["alias"] == f"{ALIAS}rank-s"
    r = client.get(
        "/v1/admin/dashboard/rankings",
        headers=admin,
        params={"tipo": "productos", "desde": DESDE, "hasta": HASTA},
    )
    assert r.status_code == 200 and r.json() == []


# ----------------------------------------------------------------- estrellas
def _evento(uid: str, ean: str, via: str | None, cuando: str, encontrado: bool = True) -> None:
    datos = f'{{"ean": "{ean}", "encontrado": {str(encontrado).lower()}'
    datos += f', "via": "{via}"}}' if via else "}"
    sql(
        "insert into eventos (tipo, ocurrio_en, usuario_id, entidad, entidad_ref, datos) "
        "values ('producto.escaneado', $1::timestamptz, $2::uuid, 'producto', $3, $4::jsonb)",
        _t(cuando),
        uid,
        ean,
        datos,
    )


def test_estrellas_cuenta_usuarios_distintos_y_filtra_por_via(client, admin):
    a, b = _usuario("est-a"), _usuario("est-b")
    popular, repetido = "7790000000024", "7790000000031"
    # `popular`: dos usuarios distintos; `repetido`: uno solo, muchas veces.
    _evento(a, popular, "camara", "2024-03-10T12:00:00Z")
    _evento(b, popular, "manual", "2024-03-10T12:05:00Z")
    for i in range(5):
        _evento(a, repetido, "camara", f"2024-03-10T13:0{i}:00Z")
    _evento(a, "7790000000048", None, "2024-03-10T14:00:00Z", encontrado=False)  # app vieja
    params = {"desde": DESDE, "hasta": HASTA}
    todos = client.get("/v1/admin/dashboard/estrellas", headers=admin, params=params).json()
    assert [(e["ean"], e["usuarios"], e["escaneos"]) for e in todos][:2] == [
        (popular, 2, 2),
        (repetido, 1, 5),
    ]
    assert {e["ean"] for e in todos} == {popular, repetido, "7790000000048"}
    camara = client.get(
        "/v1/admin/dashboard/estrellas", headers=admin, params={**params, "via": "camara"}
    ).json()
    assert [(e["ean"], e["usuarios"]) for e in camara] == [(popular, 1), (repetido, 1)] or [
        (e["ean"], e["usuarios"]) for e in camara
    ] == [(repetido, 1), (popular, 1)]
    manual = client.get(
        "/v1/admin/dashboard/estrellas", headers=admin, params={**params, "via": "manual"}
    ).json()
    assert [e["ean"] for e in manual] == [popular]
    assert (
        client.get(
            "/v1/admin/dashboard/estrellas", headers=admin, params={**params, "via": "x"}
        ).status_code
        == 422
    )
