"""Códigos de invitación (`modo_acceso = solo_invitacion`). Docs/04, §6.

La integridad (código normalizado, `usos <= usos_max`) la garantiza Postgres; acá
solo está la regla de negocio: qué es un código vigente y cuándo se gasta.
"""

from uuid import UUID

import asyncpg


def normalizar(codigo: str) -> str:
    return codigo.strip().lower()


async def consumir(pool: asyncpg.Pool, codigo: str) -> UUID | None:
    """Gasta un uso del código si existe, no venció y le quedan usos. Un único
    UPDATE condicional: dos pedidos a la vez no pasan del tope. None si no sirve
    (no se distingue el motivo: no hay que ayudar a adivinar códigos)."""
    return await pool.fetchval(
        """
        update invitaciones set usos = usos + 1
        where codigo = $1
          and (vence is null or vence > now())
          and (usos_max is null or usos < usos_max)
        returning id
        """,
        normalizar(codigo),
    )


async def devolver(pool: asyncpg.Pool, invitacion_id: UUID) -> None:
    """Devuelve el uso si el alta falló después de gastarlo (proveedor caído)."""
    await pool.execute(
        "update invitaciones set usos = usos - 1 where id = $1 and usos > 0", invitacion_id
    )
