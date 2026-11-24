"""Capa de acceso a datos genérica: asyncpg contra cualquier Postgres."""

import logging

import asyncpg
from fastapi import Request

from app.config import get_settings

log = logging.getLogger("almacenero")

# Regla de tiempo (docs/04 §11.3): la sesión siempre en UTC, la fijamos nosotros y no el
# default del proveedor de la base.
SERVER_SETTINGS = {"timezone": "UTC"}


async def verificar_utc(conn: asyncpg.Pool | asyncpg.Connection) -> bool:
    """True si la sesión está en UTC; si no, lo deja en el log (no corta el arranque)."""
    zona = await conn.fetchval("show timezone")
    if zona != "UTC":
        log.warning("la zona horaria de la sesión es %s y debería ser UTC (docs/04 §11.3)", zona)
        return False
    return True


async def create_pool() -> asyncpg.Pool:
    pool = await asyncpg.create_pool(
        get_settings().database_url, min_size=1, max_size=10, server_settings=SERVER_SETTINGS
    )
    await verificar_utc(pool)
    return pool


async def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool
