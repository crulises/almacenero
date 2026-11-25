"""Programación de ETL (docs/04 §11.4): un ciclo liviano dentro del backend que encola en la
**misma cola** `etl_ejecuciones` que el panel (así se ve en el historial y corre en su ejecutor).

- Cron en UTC (`services/cron.py`); el panel muestra la hora en Buenos Aires y guarda UTC.
- **Varias réplicas, una sola corre:** cada vuelta toma `pg_try_advisory_xact_lock` dentro de una
  transacción; quien no lo obtiene no hace nada esa vuelta. No se usa `pg_cron` (acoplaría el
  proyecto a una extensión del proveedor).
- **Umbral:** una programación activa de `eventos_exportar` con «al superar el umbral» encola además
  cuando `eventos` pasa de `config.eventos_max_filas` (como mucho una vez por hora).
- Nunca apila: si la ejecución anterior de esa programación sigue en cola o corriendo, se salta.
"""

import asyncio
import contextlib
import json
import logging
from datetime import datetime, timedelta, timezone

import asyncpg

from app.services import auditoria, cron
from app.services import config as cfg
from app.services.etl import obtener

log = logging.getLogger("almacenero.programaciones")

LOCK_ID = 7_190_019  # número fijo del advisory lock de este ciclo
VUELTA_S = 30
UMBRAL_REINTENTO = timedelta(hours=1)


async def vuelta(pool: asyncpg.Pool, ahora: datetime | None = None) -> int:
    """Una pasada: encola lo que toca. Devuelve cuántas ejecuciones encoló."""
    ahora = ahora or datetime.now(timezone.utc)
    encoladas = 0
    async with pool.acquire() as conn, conn.transaction():
        if not await conn.fetchval("select pg_try_advisory_xact_lock($1)", LOCK_ID):
            return 0  # otra réplica está en esa vuelta
        filas = await conn.fetch(
            "select * from etl_programaciones where activa order by creado_en for update"
        )
        superado: bool | None = None
        for p in filas:
            defn = obtener(p["etl"])
            if defn is None:
                continue
            toca_cron = p["proxima_corrida"] is not None and p["proxima_corrida"] <= ahora
            toca_umbral = False
            if (
                p["al_superar_umbral"]
                and p["etl"] == "eventos_exportar"
                and (p["ultima_corrida"] is None or p["ultima_corrida"] <= ahora - UMBRAL_REINTENTO)
            ):
                if superado is None:
                    tope = int(await cfg.leer(conn, "eventos_max_filas"))
                    superado = await conn.fetchval("select count(*) from eventos") > tope
                toca_umbral = superado
            if not (toca_cron or toca_umbral):
                continue
            siguiente = cron.proxima(p["cron"], ahora)
            pendiente = p["ultima_ejecucion_id"] and await conn.fetchval(
                "select estado in ('en_cola', 'corriendo', 'cancelando') "
                "from etl_ejecuciones where id = $1",
                p["ultima_ejecucion_id"],
            )
            if pendiente:
                await conn.execute(
                    "update etl_programaciones set proxima_corrida = $2 where id = $1",
                    p["id"],
                    siguiente,
                )
                continue
            id_ = await conn.fetchval(
                "insert into etl_ejecuciones (etl, parametros, ejecutor, creado_por) "
                "values ($1, $2::jsonb, $3, null) returning id",
                p["etl"],
                p["parametros"],
                defn.ejecutor,
            )
            await conn.execute(
                "update etl_programaciones set ultima_corrida = $2, proxima_corrida = $3, "
                "ultima_ejecucion_id = $4 where id = $1",
                p["id"],
                ahora,
                siguiente,
                id_,
            )
            await auditoria.registrar(
                conn, None, "programacion.ejecutar", "etl", id_, None,
                {"programacion": str(p["id"]), "etl": p["etl"],
                 "motivo": "cron" if toca_cron else "umbral de eventos",
                 "parametros": json.loads(p["parametros"])},
            )  # fmt: skip
            encoladas += 1
    return encoladas


class CicloProgramaciones:
    """Tarea de fondo del backend (como `EjecutorWeb`): llama a `vuelta` cada pocos segundos."""

    def __init__(self, pool: asyncpg.Pool, cada_s: float = VUELTA_S):
        self._pool = pool
        self._cada = cada_s
        self._parar = asyncio.Event()
        self._tarea: asyncio.Task | None = None

    def iniciar(self) -> None:
        self._tarea = asyncio.create_task(self._correr())
        log.info("ciclo de programaciones iniciado")

    async def _correr(self) -> None:
        while not self._parar.is_set():
            try:
                await vuelta(self._pool)
            except Exception:  # noqa: BLE001 - el ciclo no se muere por una vuelta mala
                log.exception("falló una vuelta de programaciones")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._parar.wait(), self._cada)

    async def detener(self) -> None:
        self._parar.set()
        if self._tarea:
            self._tarea.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._tarea
