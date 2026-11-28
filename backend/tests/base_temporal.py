"""Base de datos descartable para los tests del backend.

Los tests dan de alta usuarios, precios, locales… Antes lo hacían en la base de desarrollo y
la dejaban llena de basura (miles de cuentas de prueba). Ahora `pytest` crea una base nueva
(`almacenero_test_<id>`), le aplica las migraciones y el seed —SQL plano, el mismo camino que
`make migrate`— y la borra al terminar. La de desarrollo no se toca.

Para probar contra la base de desarrollo (no recomendado): `TESTS_EN_BASE_DE_DESARROLLO=1`.
"""

import asyncio
import atexit
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg

RAIZ = Path(__file__).resolve().parents[2]
EXTENSIONES = ("postgis", "pg_trgm", "unaccent")


def _con_base(url: str, nombre: str) -> str:
    partes = urlsplit(url)
    return urlunsplit(partes._replace(path=f"/{nombre}"))


async def _crear(url_admin: str, url_nueva: str, nombre: str) -> None:
    admin = await asyncpg.connect(url_admin)
    try:
        await admin.execute(f'create database "{nombre}"')
    finally:
        await admin.close()
    conn = await asyncpg.connect(url_nueva)
    try:
        for ext in EXTENSIONES:
            await conn.execute(f'create extension if not exists "{ext}"')
        archivos = sorted((RAIZ / "supabase" / "migrations").glob("*.sql"))
        archivos.append(RAIZ / "supabase" / "seed.sql")
        for archivo in archivos:
            await conn.execute(archivo.read_text())
    finally:
        await conn.close()


async def _borrar(url_admin: str, nombre: str) -> None:
    admin = await asyncpg.connect(url_admin)
    try:
        await admin.execute(f'drop database if exists "{nombre}" with (force)')
    finally:
        await admin.close()


def preparar() -> str | None:
    """Crea la base descartable y apunta `DATABASE_URL` a ella. Devuelve su nombre
    (o `None` si se pidió usar la de desarrollo)."""
    if os.environ.get("TESTS_EN_BASE_DE_DESARROLLO") == "1":
        return None
    from app.config import get_settings

    url_dev = get_settings().database_url
    nombre = f"almacenero_test_{uuid.uuid4().hex[:8]}"
    url_admin = _con_base(url_dev, "postgres")
    url_nueva = _con_base(url_dev, nombre)
    asyncio.run(_crear(url_admin, url_nueva, nombre))
    os.environ["DATABASE_URL"] = url_nueva
    get_settings.cache_clear()
    atexit.register(lambda: asyncio.run(_borrar(url_admin, nombre)))
    return nombre
