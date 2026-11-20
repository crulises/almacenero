"""Códigos de invitación (`modo_acceso = solo_invitacion`). Docs/04, §6.

La integridad (código normalizado, `usos <= usos_max`, uso coherente) la garantiza
Postgres; acá está la regla de negocio: qué es un código vigente, cuándo se gasta y
cómo se generan los PINs de un solo uso.
"""

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg

# Cuántos PINs distintos puede pedir un admin de una vez (el panel es manual).
MAX_LOTE = 100


def normalizar(codigo: str) -> str:
    return codigo.strip().lower()


async def consumir(pool: asyncpg.Pool, codigo: str) -> UUID | None:
    """Gasta un uso del código si existe, no venció y le quedan usos. Un único
    UPDATE condicional: dos pedidos a la vez no pasan del tope (un PIN lo usa UNA
    persona). None si no sirve (no se distingue el motivo: no hay que ayudar a
    adivinar códigos)."""
    return await pool.fetchval(
        """
        update invitaciones set usos = usos + 1, usada_at = now()
        where codigo = $1
          and (vence is null or vence > now())
          and (usos_max is null or usos < usos_max)
        returning id
        """,
        normalizar(codigo),
    )


async def anotar_usuario(pool: asyncpg.Pool, invitacion_id: UUID, auth_id: UUID) -> None:
    """Deja escrito quién usó el código (para el panel de admin)."""
    await pool.execute(
        "update invitaciones set usada_por_auth = $2 where id = $1", invitacion_id, auth_id
    )


async def devolver(pool: asyncpg.Pool, invitacion_id: UUID) -> None:
    """Devuelve el uso si el alta falló después de gastarlo (proveedor caído)."""
    await pool.execute(
        """
        update invitaciones
        set usos = usos - 1,
            usada_at = case when usos - 1 = 0 then null else usada_at end,
            usada_por_auth = case when usos - 1 = 0 then null else usada_por_auth end
        where id = $1 and usos > 0
        """,
        invitacion_id,
    )


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
