"""Historial de alias e integridad en Postgres (sin pasar por la API)."""

import asyncio
import uuid

import asyncpg
import pytest

from app.config import get_settings
from tests.conftest import make_token
from tests.db import sql


def _usuario(client) -> tuple[dict, str]:
    h = {"Authorization": f"Bearer {make_token()}"}
    return h, client.get("/v1/me", headers=h).json()["id"]


def _filas(uid: str) -> list[asyncpg.Record]:
    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            return await conn.fetch(
                "select * from usuarios_alias_historial where usuario_id = $1::uuid "
                "order by cambiado_en, id",
                uid,
            )
        finally:
            await conn.close()

    return asyncio.run(run())


def test_el_alta_deja_su_fila_de_historial(client):
    _, uid = _usuario(client)
    (fila,) = _filas(uid)
    assert fila["alias_anterior"] is None
    assert fila["alias_nuevo"].startswith("anon-")
    assert fila["origen"] == "alta" and fila["cambiado_por"] is None


def test_un_update_directo_tambien_deja_rastro_como_sistema(client):
    _, uid = _usuario(client)
    sql("update usuarios set alias = $2 where id = $1::uuid", uid, f"sis-{uuid.uuid4().hex[:6]}")
    ultima = _filas(uid)[-1]
    assert ultima["origen"] == "sistema" and ultima["alias_anterior"].startswith("anon-")


def test_el_historial_es_solo_de_lectura(client):
    _, uid = _usuario(client)
    with pytest.raises(asyncpg.RaiseError):
        sql(
            "update usuarios_alias_historial set alias_nuevo = 'x' where usuario_id = $1::uuid", uid
        )
    with pytest.raises(asyncpg.RaiseError):
        sql("delete from usuarios_alias_historial where usuario_id = $1::uuid", uid)


def test_el_alias_es_unico_sin_distinguir_mayusculas(client):
    _, a = _usuario(client)
    _, b = _usuario(client)
    nombre = f"Uni{uuid.uuid4().hex[:6]}"
    sql("update usuarios set alias = $2 where id = $1::uuid", a, nombre)
    with pytest.raises(asyncpg.UniqueViolationError):
        sql("update usuarios set alias = $2 where id = $1::uuid", b, nombre.lower())


def test_los_anon_no_cuentan_para_la_unicidad(client):
    _, a = _usuario(client)
    _, b = _usuario(client)
    sql("update usuarios set alias = 'anon-zzzzzz' where id = $1::uuid", a)
    sql("update usuarios set alias = 'anon-zzzzzz' where id = $1::uuid", b)
    sql("update usuarios set alias = 'anon-a1' where id in ($1::uuid, $2::uuid)", a, b)
