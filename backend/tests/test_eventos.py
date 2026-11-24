"""Eventos de producto (docs/04 §11.2): tabla genérica + registro de tipos + POST /v1/eventos.
Contra Postgres real."""

import asyncio

import asyncpg
import pytest

from app.config import get_settings
from app.services import eventos
from tests.db import sql


def _filas(user_id: str) -> list[asyncpg.Record]:
    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            return await conn.fetch(
                "select tipo, ocurrio_en, entidad, entidad_ref, datos::text as datos "
                "from eventos where usuario_id = $1::uuid order by id",
                user_id,
            )
        finally:
            await conn.close()

    return asyncio.run(run())


@pytest.fixture
def yo(client, auth):
    return client.get("/v1/me", headers=auth).json()["id"]


def _post(client, auth, lista):
    return client.post("/v1/eventos", json={"eventos": lista}, headers=auth)


def test_exige_login(client):
    assert client.post("/v1/eventos", json={"eventos": []}).status_code == 401


def test_guarda_un_escaneo_con_instante_del_servidor(client, auth, yo):
    r = _post(
        client,
        auth,
        [{"tipo": "producto.escaneado", "datos": {"ean": "7790070411112", "encontrado": True}}],
    )
    assert r.status_code == 201, r.text
    assert r.json() == {"guardados": 1}
    (f,) = _filas(yo)
    assert f["tipo"] == "producto.escaneado"
    assert f["entidad"] == "producto"
    assert f["entidad_ref"] == "7790070411112"
    assert f["ocurrio_en"].tzinfo is not None


def test_app_abierta_no_lleva_entidad(client, auth, yo):
    assert _post(client, auth, [{"tipo": "app.abierta"}]).status_code == 201
    (f,) = _filas(yo)
    assert (f["tipo"], f["entidad"], f["entidad_ref"]) == ("app.abierta", None, None)


def test_el_reloj_del_cliente_va_a_datos_y_no_a_ocurrio_en(client, auth, yo):
    r = _post(client, auth, [{"tipo": "app.abierta", "ocurrio_en_cliente": "2001-02-03T04:05:06Z"}])
    assert r.status_code == 201, r.text
    (f,) = _filas(yo)
    assert "2001-02-03" in f["datos"]
    assert f["ocurrio_en"].year >= 2026  # lo puso el servidor


def test_tipo_desconocido_da_400_con_la_regla(client, auth, yo):
    r = _post(client, auth, [{"tipo": "inventado.cualquiera"}])
    assert r.status_code == 400
    d = r.json()["detail"]
    assert d["codigo"] == "evento_tipo_desconocido"
    assert d["como_resolver"]
    assert _filas(yo) == []


def test_un_lote_con_un_tipo_malo_no_guarda_nada(client, auth, yo):
    r = _post(client, auth, [{"tipo": "app.abierta"}, {"tipo": "nope"}])
    assert r.status_code == 400
    assert _filas(yo) == []


def test_datos_invalidos_dan_422_con_la_regla(client, auth, yo):
    r = _post(
        client, auth, [{"tipo": "producto.escaneado", "datos": {"ean": "abc", "encontrado": True}}]
    )
    assert r.status_code == 422
    assert r.json()["detail"]["codigo"] == "evento_datos_invalidos"
    assert _filas(yo) == []


def test_datos_con_campos_de_mas_se_rechazan(client, auth, yo):
    """Privacidad: no entra texto libre ni ubicación aunque la app lo mande."""
    r = _post(
        client,
        auth,
        [
            {
                "tipo": "producto.escaneado",
                "datos": {"ean": "7790070411112", "encontrado": True, "lat": -34.6},
            }
        ],
    )
    assert r.status_code == 422
    assert _filas(yo) == []


def test_mas_de_50_se_rechaza(client, auth):
    r = _post(client, auth, [{"tipo": "app.abierta"}] * 51)
    assert r.status_code == 422


def test_un_tipo_solo_del_backend_no_lo_acepta_la_app(client, auth, yo, monkeypatch):
    monkeypatch.setitem(
        eventos.TIPOS,
        "solo.backend",
        eventos.TipoEvento(datos=eventos.DatosVacios, desde_app=False),
    )
    r = _post(client, auth, [{"tipo": "solo.backend"}])
    assert r.status_code == 400
    assert r.json()["detail"]["codigo"] == "evento_tipo_desconocido"


def test_rate_limit_por_usuario(client, auth, config_temporal):
    config_temporal("max_lotes_eventos_por_hora", "2")
    assert _post(client, auth, [{"tipo": "app.abierta"}]).status_code == 201
    assert _post(client, auth, [{"tipo": "app.abierta"}]).status_code == 201
    r = _post(client, auth, [{"tipo": "app.abierta"}])
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_el_usuario_borrado_deja_el_evento_huerfano(client, auth, yo):
    _post(client, auth, [{"tipo": "app.abierta"}])
    sql("delete from usuarios where id = $1::uuid", yo)
    n = asyncio.run(_contar_huerfanos())
    assert n >= 1


async def _contar_huerfanos() -> int:
    conn = await asyncpg.connect(get_settings().database_url)
    try:
        return await conn.fetchval("select count(*) from eventos where usuario_id is null")
    finally:
        await conn.close()


def test_el_tipo_tiene_que_tener_formato(client):
    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            await conn.execute("insert into eventos (tipo) values ('Mal Tipo')")
        finally:
            await conn.close()

    with pytest.raises(asyncpg.CheckViolationError):
        asyncio.run(run())
