"""Identificador de dispositivo (docs/04 §9, «Dispositivo»).

La app manda el ANDROID_ID en el header `X-Device-Id`. Acá solo se guarda su hash. La
regla de negocio: un dispositivo asociado a una cuenta de baja no puede crear otra.
"""

import hashlib
from uuid import UUID

import asyncpg

LARGO_MIN, LARGO_MAX = 8, 128


def hashear(valor: str | None) -> str | None:
    """sha256 del ID, o None si falta o no tiene pinta de ID (no rompe la app)."""
    if valor is None:
        return None
    valor = valor.strip().lower()
    if not LARGO_MIN <= len(valor) <= LARGO_MAX:
        return None
    return hashlib.sha256(f"almacenero:{valor}".encode()).hexdigest()


async def tiene_baja(pool: asyncpg.Pool, hash_: str) -> bool:
    """¿Alguna cuenta de baja usó este dispositivo?"""
    return bool(
        await pool.fetchval(
            """
            select exists (
                select 1 from dispositivos d join usuarios u on u.auth_id = d.auth_id
                where d.hash = $1 and u.estado = 'baja'
            )
            """,
            hash_,
        )
    )


async def registrar(pool: asyncpg.Pool, hash_: str, auth_id: UUID) -> None:
    await pool.execute(
        """
        insert into dispositivos (hash, auth_id) values ($1, $2)
        on conflict (hash, auth_id) do update set ultima_vez = now()
        where dispositivos.ultima_vez < now() - interval '1 hour'
        """,
        hash_,
        auth_id,
    )


async def cuentas_del_dispositivo(pool: asyncpg.Pool, usuario_id: UUID) -> list[asyncpg.Record]:
    """Otras cuentas que usaron algún dispositivo de este usuario."""
    return await pool.fetch(
        """
        select distinct u.id, u.alias, u.estado
        from usuarios me
        join dispositivos d1 on d1.auth_id = me.auth_id
        join dispositivos d2 on d2.hash = d1.hash and d2.auth_id <> d1.auth_id
        join usuarios u on u.auth_id = d2.auth_id
        where me.id = $1
        order by u.alias
        """,
        usuario_id,
    )
