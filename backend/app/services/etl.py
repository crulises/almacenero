"""Puente del backend con el ETL del repo (`etl/`): el ejecutor `web` de la cola (docs/04 §10-A).

`etl/` está al lado de `backend/` en el repo y en la imagen se copia junto a `app/`. Se agrega
la raíz al `sys.path` por si el backend corre desde otra carpeta (tests, `uvicorn` a mano).
"""

import asyncio
import contextlib
import logging
import sys
from pathlib import Path

log = logging.getLogger("almacenero.etl")


def _asegurar_etl() -> None:
    try:
        import etl  # noqa: F401
    except ImportError:
        for padre in Path(__file__).resolve().parents:
            if (padre / "etl" / "__init__.py").exists():
                sys.path.insert(0, str(padre))
                return
        raise


_asegurar_etl()

from etl.ejecucion import bucle  # noqa: E402
from etl.registro import (  # noqa: E402,F401
    Definicion,
    ParametroInvalido,
    describir,
    obtener,
    todas,
    validar,
)


class EjecutorWeb:
    """Tarea de fondo del backend: corre las ejecuciones `web` de la cola, una por vez."""

    def __init__(self, url: str, mem_mb: int, max_s: int):
        self._parar = asyncio.Event()
        self._tarea: asyncio.Task | None = None
        self._args = (url, "web", self._parar)
        self._opciones = {"mem_mb": mem_mb, "max_s": max_s}

    def iniciar(self) -> None:
        self._tarea = asyncio.create_task(bucle(*self._args, **self._opciones))
        log.info("ejecutor web de ETL iniciado")

    async def detener(self) -> None:
        self._parar.set()
        if self._tarea:
            self._tarea.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._tarea
