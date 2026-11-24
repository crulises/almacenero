"""Códigos de invitación (`modo_acceso = solo_invitacion`). Docs/04, §6.

La integridad (código normalizado, `usos <= usos_max`, uso coherente) la garantiza
Postgres; acá está la regla de negocio: qué es un código vigente, cuándo se gasta y
cómo se generan los PINs de un solo uso.
"""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg

# Cuántos PINs distintos puede pedir un admin de una vez (el panel es manual).
MAX_LOTE = 100


def normalizar(codigo: str) -> str:
    return codigo.strip().lower()


@dataclass(frozen=True)
class Uso:
    """Un uso gastado: la invitación y la fila de `invitaciones_usos` que lo registra."""

    invitacion_id: UUID
    uso_id: int


async def consumir(pool: asyncpg.Pool, codigo: str) -> Uso | None:
    """Gasta un uso del código si existe, no venció y le quedan usos, y lo anota en
    `invitaciones_usos` (docs/04 §11). Un único UPDATE condicional: dos pedidos a la vez no pasan
    del tope (un PIN lo usa UNA persona). None si no sirve (no se distingue el motivo: no hay
    que ayudar a adivinar códigos)."""
    async with pool.acquire() as conn, conn.transaction():
        invitacion_id = await conn.fetchval(
            """
            update invitaciones set usos = usos + 1, usada_at = now()
            where codigo = $1
              and (vence is null or vence > now())
              and (usos_max is null or usos < usos_max)
            returning id
            """,
            normalizar(codigo),
        )
        if invitacion_id is None:
            return None
        uso_id = await conn.fetchval(
            "insert into invitaciones_usos (invitacion_id) values ($1) returning id", invitacion_id
        )
        return Uso(invitacion_id, uso_id)


async def anotar_usuario(pool: asyncpg.Pool, uso: Uso, auth_id: UUID) -> None:
    """Deja escrito quién usó el código (para el panel de admin y la serie del dashboard)."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "update invitaciones set usada_por_auth = $2 where id = $1", uso.invitacion_id, auth_id
        )
        await conn.execute(
            "update invitaciones_usos set auth_id = $2 where id = $1", uso.uso_id, auth_id
        )


async def devolver(pool: asyncpg.Pool, uso: Uso) -> None:
    """Devuelve el uso si el alta falló después de gastarlo (proveedor caído): baja el contador
    y borra la fila de ese uso."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """
            update invitaciones
            set usos = usos - 1,
                usada_at = case when usos - 1 = 0 then null else usada_at end,
                usada_por_auth = case when usos - 1 = 0 then null else usada_por_auth end
            where id = $1 and usos > 0
            """,
            uso.invitacion_id,
        )
        await conn.execute("delete from invitaciones_usos where id = $1", uso.uso_id)


def pin_al_azar() -> str:
    """6 dígitos, con ceros a la izquierda. `secrets`, no `random`: no tiene que ser
    predecible."""
    return f"{secrets.randbelow(1_000_000):06d}"


async def crear_pines(
    conn: asyncpg.Connection,
    cantidad: int,
    nota: str | None,
    vigencia_horas: int | None,
    creada_por: UUID,
) -> list[asyncpg.Record]:
    """Crea `cantidad` PINs de un solo uso. Si un PIN ya existe (usado o no) se sortea
    otro: el UNIQUE de `codigo` decide, no una lectura previa (sin carreras)."""
    vence = datetime.now(timezone.utc) + timedelta(hours=vigencia_horas) if vigencia_horas else None
    creados: list[asyncpg.Record] = []
    intentos = 0
    while len(creados) < cantidad:
        intentos += 1
        if intentos > cantidad * 20:  # con 1.000.000 de PINs, solo si casi no quedan libres
            raise RuntimeError("no hay PINs libres: demasiados códigos ya emitidos")
        fila = await conn.fetchrow(
            """
            insert into invitaciones (codigo, usos_max, vence, nota, creada_por)
            values ($1, 1, $2, $3, $4)
            on conflict (codigo) do nothing
            returning id, codigo, nota, vence, created_at
            """,
            pin_al_azar(),
            vence,
            nota,
            creada_por,
        )
        if fila is not None:
            creados.append(fila)
    return creados
