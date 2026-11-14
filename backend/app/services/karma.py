"""Lógica de negocio del karma (v0.0.1: solo karma básico por carga).

Validación colaborativa, penalizaciones y premios por karma bajo: fuera de alcance.
"""

import asyncpg

KARMA_POR_CARGA = 1


def karma_por_carga(config: dict[str, object] | None = None) -> int:
    """Karma que otorga una carga de precio. Tunable vía `config.karma_por_carga`."""
    if config and isinstance(config.get("karma_por_carga"), int):
        return int(config["karma_por_carga"])  # type: ignore[arg-type]
    return KARMA_POR_CARGA


async def sumar_karma(conn: asyncpg.Connection, user_id, puntos: int) -> int:
    """Suma karma. Debe llamarse dentro de una transacción: habilita la escritura
    de karma (protegida por trigger) solo para esa transacción."""
    await conn.execute("select set_config('app.karma_write', 'on', true)")
    return await conn.fetchval(
        "update usuarios set karma = karma + $2 where id = $1 returning karma",
        user_id,
        puntos,
    )
