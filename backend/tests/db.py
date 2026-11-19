"""Acceso directo a la base desde los tests (para preparar y limpiar estado)."""

import asyncio

import asyncpg

from app.config import get_settings


def sql(query: str, *args):
    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            return await conn.execute(query, *args)
        finally:
            await conn.close()

    return asyncio.run(run())


def hacer_admin(user_id: str) -> None:
    """Promueve a admin como lo hace `make admin`: habilitando la escritura del rol
    solo dentro de esa transacción."""

    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            async with conn.transaction():
                await conn.execute("select set_config('app.rol_write', 'on', true)")
                await conn.execute("update usuarios set rol = 'admin' where id = $1::uuid", user_id)
        finally:
            await conn.close()

    asyncio.run(run())


def valor_config(clave: str):
    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            return await conn.fetchval(
                "select valor::text from config where clave = $1 and rubro is null", clave
            )
        finally:
            await conn.close()

    return asyncio.run(run())


def cuerpo_carga(local_id: str, ean: str, precio: str, **extra) -> dict:
    """Cuerpo de `POST /v1/precios` desde el mismo punto del local (dentro del geofence)."""

    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            return await conn.fetchrow(
                "select st_y(ubicacion::geometry) as lat, st_x(ubicacion::geometry) as lng "
                "from locales where id = $1::uuid",
                local_id,
            )
        finally:
            await conn.close()

    punto = asyncio.run(run())
    if punto is None:  # local inexistente: sirve para probar el 404
        punto = {"lat": 0.0, "lng": 0.0}
    return {
        "ean": ean,
        "local_id": local_id,
        "precio": precio,
        "lat": punto["lat"],
        "lng": punto["lng"],
        "precision_m": 10,
        **extra,
    }
