"""Escalera de moderación por karma (docs/04 §9).

El escalón NO se guarda: se deduce del karma y de dos umbrales de `config`. Así un karma
que sube (ajuste del admin, cargas, una validación futura) levanta la restricción solo, y
una penalización automática futura solo tiene que restar karma: la escalera ya está.
"""

import json

import asyncpg

from app.services import config

NORMAL = "normal"
AVISO = "aviso"
RESTRINGIDO = "restringido"

_CLAVES = ("karma_umbral_aviso", "karma_umbral_restriccion")


def escalon(karma: int, umbral_aviso: int, umbral_restriccion: int) -> str:
    """`karma <= umbral`. Si el admin dejó la restricción por encima del aviso, manda la
    restricción (el escalón más duro que corresponda)."""
    if karma <= umbral_restriccion:
        return RESTRINGIDO
    if karma <= umbral_aviso:
        return AVISO
    return NORMAL


async def umbrales(conn: asyncpg.Pool | asyncpg.Connection) -> tuple[int, int]:
    """(aviso, restricción), con el default del código si falta la fila. Una sola
    consulta: esto corre en cada request autenticado."""
    rows = await conn.fetch(
        "select clave, valor::text as valor from config where clave = any($1) and rubro is null",
        list(_CLAVES),
    )
    valores = {r["clave"]: json.loads(r["valor"]) for r in rows}
    aviso, restriccion = (int(valores.get(c, config.DEFAULTS[c])) for c in _CLAVES)
    return aviso, restriccion


async def escalon_de(
    conn: asyncpg.Pool | asyncpg.Connection, karma: int, rol: str = "usuario"
) -> str:
    """Escalón de un usuario. Un admin nunca se restringe por karma."""
    if rol == "admin":
        return NORMAL
    aviso, restriccion = await umbrales(conn)
    return escalon(karma, aviso, restriccion)
