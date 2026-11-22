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
    hacer_rol(user_id, "admin")


def hacer_rol(user_id: str, rol: str) -> None:

    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            async with conn.transaction():
                await conn.execute("select set_config('app.rol_write', 'on', true)")
                await conn.execute("update usuarios set rol = $2 where id = $1::uuid", user_id, rol)
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


def poner_karma(user_id: str, karma: int) -> None:
    """Fija el karma como lo haría un admin: habilitando la escritura solo en la transacción."""

    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            async with conn.transaction():
                await conn.execute("select set_config('app.karma_write', 'on', true)")
                await conn.execute(
                    "update usuarios set karma = $2 where id = $1::uuid", user_id, karma
                )
        finally:
            await conn.close()

    asyncio.run(run())


def poner_estado_sin_fecha(user_id: str, estado: str) -> None:
    """Cambia SOLO `estado` con la escritura habilitada (para probar el check de coherencia)."""

    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            async with conn.transaction():
                await conn.execute("select set_config('app.estado_write', 'on', true)")
                await conn.execute(
                    "update usuarios set estado = $2 where id = $1::uuid", user_id, estado
                )
        finally:
            await conn.close()

    asyncio.run(run())
