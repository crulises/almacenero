"""Integridad en Postgres: lo que la base garantiza sin depender del backend."""

import asyncio

import asyncpg
import pytest

from app.config import get_settings
from tests.conftest import make_token


def _sql(query: str, *args):
    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            return await conn.execute(query, *args)
        finally:
            await conn.close()

    return asyncio.run(run())


@pytest.fixture
def usuario(client, auth):
    return client.get("/v1/me", headers=auth).json()["id"]


def test_el_karma_no_se_modifica_a_mano(usuario):
    with pytest.raises(asyncpg.PostgresError, match="karma"):
        _sql("update usuarios set karma = 999 where id = $1::uuid", usuario)


def test_no_se_puede_crear_un_usuario_con_karma(usuario):
    with pytest.raises(asyncpg.PostgresError, match="karma"):
        _sql(
            "insert into usuarios (auth_id, alias, karma) "
            "values (gen_random_uuid(), 'tramposo', 50)"
        )


def test_un_precio_apunta_a_exactamente_un_tipo_de_producto(usuario):
    # sin producto canónico ni genérico: viola el CHECK
    with pytest.raises(asyncpg.CheckViolationError):
        _sql(
            "insert into precios (local_id, precio, user_id) "
            "select l.id, 10, $1::uuid from locales l limit 1",
            usuario,
        )


def test_el_rol_no_se_modifica_a_mano(usuario):
    with pytest.raises(asyncpg.PostgresError, match="rol"):
        _sql("update usuarios set rol = 'admin' where id = $1::uuid", usuario)


def test_no_se_puede_crear_un_usuario_admin_a_mano():
    with pytest.raises(asyncpg.PostgresError, match="rol"):
        _sql(
            "insert into usuarios (auth_id, alias, rol) "
            "values (gen_random_uuid(), 'colado', 'admin')"
        )


def test_el_rol_solo_admite_valores_conocidos(usuario):
    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            async with conn.transaction():
                await conn.execute("select set_config('app.rol_write', 'on', true)")
                await conn.execute("update usuarios set rol = 'dios' where id = $1::uuid", usuario)
        finally:
            await conn.close()

    with pytest.raises(asyncpg.CheckViolationError):
        asyncio.run(run())


def _con_estado_write(query: str, *args):
    """Corre `query` en una transacción que habilita la escritura del estado (como el panel)."""

    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            async with conn.transaction():
                await conn.execute("select set_config('app.estado_write', 'on', true)")
                return await conn.execute(query, *args)
        finally:
            await conn.close()

    return asyncio.run(run())


def test_estado_fusionada_requiere_destino(usuario):
    with pytest.raises(asyncpg.PostgresError, match="usuarios_fusionada_coherente"):
        _con_estado_write("update usuarios set estado = 'fusionada' where id = $1::uuid", usuario)


def test_estado_fusionada_no_puede_apuntar_a_si_mismo(usuario):
    with pytest.raises(asyncpg.PostgresError, match="usuarios_fusionada_coherente"):
        _con_estado_write(
            "update usuarios set estado = 'fusionada', fusionada_en = id where id = $1::uuid",
            usuario,
        )


def test_estado_fusionada_con_destino_pasa(client, usuario):
    otro = client.get("/v1/me", headers={"Authorization": f"Bearer {make_token()}"}).json()["id"]
    _con_estado_write(
        "update usuarios set estado = 'fusionada', fusionada_en = $2::uuid where id = $1::uuid",
        usuario,
        otro,
    )


def test_fusionada_no_se_setea_sin_habilitar_la_escritura(client, usuario):
    with pytest.raises(asyncpg.PostgresError, match="estado"):
        _sql(
            "update usuarios set estado = 'fusionada', fusionada_en = id where id = $1::uuid",
            usuario,
        )
