"""Rastro de las correcciones del admin (`auditoria_admin`, append-only en Postgres).

Se registra en la MISMA transacción que la corrección: o quedan las dos o ninguna.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg


def _default(o: Any) -> Any:
    if isinstance(o, Decimal | UUID):
        return str(o)
    if isinstance(o, datetime | date):
        return o.isoformat()
    raise TypeError(f"no serializable: {type(o)}")


def a_json(valor: Any) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, asyncpg.Record):
        valor = dict(valor)
    return json.dumps(valor, default=_default, ensure_ascii=False)


async def registrar(
    conn: asyncpg.Connection,
    admin_id: UUID | None,  # None: lo hizo el sistema (p. ej. una programación)
    accion: str,
    entidad: str,
    entidad_id: Any,
    antes: Any = None,
    despues: Any = None,
    nota: str | None = None,
) -> None:
    await conn.execute(
        """
        insert into auditoria_admin (usuario_id, accion, entidad, entidad_id, antes, despues, nota)
        values ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7)
        """,
        admin_id,
        accion,
        entidad,
        str(entidad_id),
        a_json(antes),
        a_json(despues),
        nota,
    )
