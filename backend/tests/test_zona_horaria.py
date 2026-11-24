"""Zona horaria (docs/04 §11.3, reglas 1 y 2): todo instante es `timestamptz` y cada conexión
nuestra abre con la sesión en UTC, sin depender del default del proveedor."""

import asyncio

import asyncpg

from app.config import get_settings
from app.db import create_pool, verificar_utc


def test_no_hay_columnas_timestamp_sin_zona():
    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            return await conn.fetch(
                """
                select table_name, column_name from information_schema.columns
                where table_schema = 'public' and data_type = 'timestamp without time zone'
                """
            )
        finally:
            await conn.close()

    assert [tuple(r) for r in asyncio.run(run())] == []


def test_el_pool_abre_las_conexiones_en_utc():
    async def run():
        pool = await create_pool()
        try:
            return await pool.fetchval("show timezone")
        finally:
            await pool.close()

    assert asyncio.run(run()) == "UTC"


def test_la_conexion_del_etl_abre_en_utc():
    from etl.comun.catalogo import conectar

    async def run():
        conn = await conectar()
        try:
            return await conn.fetchval("show timezone")
        finally:
            await conn.close()

    assert asyncio.run(run()) == "UTC"


def test_verificar_utc_avisa_si_la_zona_no_es_utc(caplog):
    async def run():
        conn = await asyncpg.connect(
            get_settings().database_url, server_settings={"timezone": "Asia/Tokyo"}
        )
        try:
            return await verificar_utc(conn)
        finally:
            await conn.close()

    with caplog.at_level("WARNING", logger="almacenero"):
        assert asyncio.run(run()) is False
    assert "UTC" in caplog.text
