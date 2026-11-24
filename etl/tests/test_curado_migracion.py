"""Migración del corte 17: fuente `curado`, su prioridad y la tabla `catalogo_lotes`."""

import asyncio

import asyncpg
import pytest

from etl.comun.catalogo import database_url

EAN = "7999900000017"  # el dígito no importa: solo se inserta, no se valida con GS1


def db(coro_fn):
    async def run():
        conn = await asyncpg.connect(database_url())
        try:
            return await coro_fn(conn)
        finally:
            await conn.close()

    return asyncio.run(run())


@pytest.fixture(autouse=True)
def limpio():
    async def borrar(c):
        await c.execute("delete from producto_fuentes where ean = $1", EAN)
        await c.execute("delete from productos_canonicos where ean = $1", EAN)
        await c.execute("delete from catalogo_lotes where nombre_archivo = 'test-migracion.csv'")

    db(borrar)
    yield
    db(borrar)


def test_curado_va_entre_manual_y_sepa():
    async def run(c):
        return [
            await c.fetchval("select prioridad_fuente($1)", f)
            for f in ("manual", "curado", "sepa", "off")
        ]

    manual, curado, sepa, off = db(run)
    assert manual < curado < sepa < off


def test_curado_es_origen_y_fuente_validos():
    async def run(c):
        await c.execute(
            "insert into productos_canonicos (ean, nombre, origen) values ($1, 'Algo', 'curado')",
            EAN,
        )
        await c.execute(
            "insert into producto_fuentes (ean, fuente, datos) values ($1, 'curado', '{}')", EAN
        )

    db(run)


def test_lote_exige_sha256_de_64_hex():
    async def run(c, sha):
        await c.execute(
            "insert into catalogo_lotes (formato, version_normalizador, nombre_archivo, sha256,"
            " filas, nuevos, cambiados, iguales, invalidos) values"
            " ('catalogo_curado_v1', 1, 'test-migracion.csv', $1, 0, 0, 0, 0, 0)",
            sha,
        )

    db(lambda c: run(c, "a" * 64))
    with pytest.raises(asyncpg.CheckViolationError):
        db(lambda c: run(c, "xyz"))
