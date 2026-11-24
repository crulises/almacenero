"""Supervisor de la cola de ETL (docs/04 §10-A): toma una ejecución, la corre en un subproceso
(`python -m etl.ejecutar <id>`), renueva el latido, pasa su salida al log y obedece la
cancelación. Lo usan el backend (ejecutor `web`) y el worker local (`make etl-worker`).

Una sola ejecución a la vez por ejecutor (lo garantiza un índice único parcial). Cada lote del
ETL es su propia transacción: cortar el proceso en cualquier momento no deja datos a medias.
"""

import asyncio
import contextlib
import json
import os
import signal
import sys
import time
from pathlib import Path

import asyncpg

from etl.ejecutar import MARCA
from etl.registro import obtener

LOG_MAX = 64 * 1024
LATIDO_MUERTO_S = 120
ARCHIVO_VIDA_H = 24


async def tomar(conn: asyncpg.Connection, ejecutor: str) -> asyncpg.Record | None:
    """Pasa la ejecución más vieja en cola de este ejecutor a `corriendo` (skip locked)."""
    try:
        return await conn.fetchrow(
            """
            update etl_ejecuciones set estado = 'corriendo', iniciado_en = now(), latido_en = now()
             where id = (select id from etl_ejecuciones
                          where estado = 'en_cola' and ejecutor = $1
                          order by creado_en for update skip locked limit 1)
            returning *
            """,
            ejecutor,
        )
    except asyncpg.UniqueViolationError:  # ya hay una corriendo en este ejecutor
        return None


async def recuperar_huerfanas(conn: asyncpg.Connection, ejecutor: str, segundos: int) -> int:
    """Una ejecución `corriendo` sin latido hace `segundos` es de un ejecutor que se murió."""
    r = await conn.execute(
        """
        update etl_ejecuciones
           set estado = 'fallo', terminado_en = now(),
               log = right(log || E'\\n[sin latido: el ejecutor se detuvo]', $3)
         where ejecutor = $1 and estado in ('corriendo', 'cancelando')
           and latido_en < now() - make_interval(secs => $2)
        """,
        ejecutor,
        float(segundos),
        LOG_MAX,
    )
    return int(r.split()[-1])


async def _terminar(conn, id_, estado: str, reporte=None, filas=None, extra_log: str = "") -> None:
    await conn.execute(
        """
        update etl_ejecuciones
           set estado = $2, terminado_en = now(), reporte = $3::jsonb, filas = $4,
               log = right(log || $5, $6)
         where id = $1
        """,
        id_,
        estado,
        json.dumps(reporte) if reporte is not None else None,
        filas,
        extra_log,
        LOG_MAX,
    )


def _limite_de_memoria(mem_mb: int | None):
    if not mem_mb or not sys.platform.startswith("linux"):
        return None
    import resource

    def aplicar() -> None:
        b = mem_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (b, b))

    return aplicar


async def _cortar(proc: asyncio.subprocess.Process, gracia_s: float) -> None:
    with contextlib.suppress(ProcessLookupError):
        proc.send_signal(signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), gracia_s)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()


async def _purgar_archivos(conn: asyncpg.Connection) -> None:
    await conn.execute(
        "delete from etl_archivos where creado_en < now() - make_interval(hours => $1)",
        ARCHIVO_VIDA_H,
    )


async def _consumir_archivos(conn: asyncpg.Connection, ej: asyncpg.Record) -> None:
    """Borra los archivos que esta ejecución ya no necesita (docs/04 §10-A)."""
    defn = obtener(ej["etl"])
    if defn is None:
        return
    params = json.loads(ej["parametros"])
    if defn.consume_archivo_con is not None and not params.get(defn.consume_archivo_con):
        return  # p. ej. un simulacro: el archivo se queda para confirmar
    for p in defn.parametros:
        if p.tipo == "archivo" and isinstance(params.get(p.nombre), dict):
            await conn.execute(
                "delete from etl_archivos where id = $1::uuid", params[p.nombre]["id"]
            )


async def correr(
    conn: asyncpg.Connection,
    ej: asyncpg.Record,
    *,
    max_s: float,
    mem_mb: int | None = None,
    latido_s: float = 2.0,
    gracia_s: float = 30.0,
) -> str:
    """Corre una ejecución ya tomada hasta el final. -> estado final."""
    id_ = ej["id"]
    entorno = {**os.environ, "PYTHONUNBUFFERED": "1"}
    raiz = Path(__file__).resolve().parent.parent
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "etl.ejecutar",
        str(id_),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=entorno,
        cwd=raiz,
        preexec_fn=_limite_de_memoria(mem_mb),
    )
    pendiente: list[str] = []
    marca: dict = {}

    async def leer() -> None:
        assert proc.stdout is not None
        async for crudo in proc.stdout:
            linea = crudo.decode("utf-8", errors="replace")
            if linea.startswith(MARCA):
                with contextlib.suppress(ValueError):
                    marca.update(json.loads(linea[len(MARCA) :]))
            else:
                pendiente.append(linea)

    lector = asyncio.create_task(leer())
    inicio = time.monotonic()
    motivo: str | None = None
    try:
        while not lector.done():
            await asyncio.wait({lector}, timeout=latido_s)
            texto, pendiente[:] = "".join(pendiente), []
            cancelar = await conn.fetchval(
                "update etl_ejecuciones set latido_en = now(), log = right(log || $2, $3),"
                " estado = case when cancelar and estado = 'corriendo' then 'cancelando'"
                " else estado end where id = $1 returning cancelar",
                id_,
                texto,
                LOG_MAX,
            )
            if cancelar and not lector.done():
                motivo = "cancelada"
                await _cortar(proc, gracia_s)
                break
            if time.monotonic() - inicio > max_s and not lector.done():
                motivo = "tiempo"
                await _cortar(proc, gracia_s)
                break
        with contextlib.suppress(Exception):
            await asyncio.wait_for(lector, 5)
        codigo = await proc.wait()
    finally:
        if not lector.done():
            lector.cancel()
        if (
            proc.returncode is None
        ):  # nos cancelaron (p. ej. el backend se apaga): no dejar huérfano
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
    resto = "".join(pendiente)
    if motivo == "cancelada":
        estado, nota = "cancelada", "\n[cancelada por el admin]\n"
    elif motivo == "tiempo":
        estado, nota = "fallo", f"\n[se pasó del tiempo máximo ({int(max_s)} s): cortada]\n"
    elif codigo == 0:
        estado, nota = "ok", ""
    else:
        estado, nota = "fallo", f"\n[el proceso terminó con código {codigo}]\n"
    await _terminar(
        conn,
        id_,
        estado,
        marca.get("reporte") if estado == "ok" else None,
        marca.get("filas"),
        resto + nota,
    )
    await _consumir_archivos(conn, ej)
    return estado


async def ciclo(
    conn: asyncpg.Connection,
    ejecutor: str,
    *,
    max_s: float = 1800,
    mem_mb: int | None = None,
    latido_s: float = 2.0,
    gracia_s: float = 30.0,
) -> bool:
    """Una vuelta: limpia, toma la próxima y la corre. -> si corrió algo."""
    await recuperar_huerfanas(conn, ejecutor, LATIDO_MUERTO_S)
    await _purgar_archivos(conn)
    ej = await tomar(conn, ejecutor)
    if ej is None:
        return False
    await correr(conn, ej, max_s=max_s, mem_mb=mem_mb, latido_s=latido_s, gracia_s=gracia_s)
    return True


async def bucle(
    url: str, ejecutor: str, parar: asyncio.Event, *, espera_s: float = 3.0, **opciones
) -> None:
    """Hasta que `parar` se active: una vuelta cada `espera_s` si no había trabajo."""
    while not parar.is_set():
        try:
            conn = await asyncpg.connect(url, server_settings={"timezone": "UTC"})
            try:
                while not parar.is_set():
                    if not await ciclo(conn, ejecutor, **opciones):
                        with contextlib.suppress(asyncio.TimeoutError):
                            await asyncio.wait_for(parar.wait(), espera_s)
            finally:
                await conn.close()
        except (OSError, asyncpg.PostgresError) as e:
            print(f"[etl] sin conexión a la base ({e}); reintento", file=sys.stderr, flush=True)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(parar.wait(), 10)
