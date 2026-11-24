"""Corre UNA ejecución de la cola, en su propio proceso: `python -m etl.ejecutar <id>`.

Lo lanza el supervisor (`etl/ejecucion.py`), sea el del backend (ejecutor `web`) o el worker
local (`make etl-worker`). Un proceso aparte (y no un hilo) permite ponerle tope de memoria y de
tiempo, y cortarlo limpio para cancelar. Todo lo que imprime va al log de la ejecución; la última
línea `@@REPORTE {...}` lleva el reporte y la cantidad de filas, y el supervisor la saca del log.
"""

import asyncio
import json
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from uuid import UUID

from etl.comun.catalogo import conectar
from etl.registro import obtener

MARCA = "@@REPORTE "


class Ctx:
    def __init__(self, ejecucion_id: UUID, usuario_id: UUID | None):
        self.ejecucion_id = ejecucion_id
        self.usuario_id = usuario_id
        self.nombres: dict[str, str] = {}  # parámetro archivo -> nombre original subido
        self.filas: int | None = None

    def log(self, texto: str) -> None:
        print(texto, flush=True)


def _nombre_seguro(nombre: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(nombre).name) or "archivo"


async def _correr(ejecucion_id: UUID, carpeta: Path) -> int:
    conn = await conectar()
    try:
        fila = await conn.fetchrow(
            "select etl, parametros, creado_por from etl_ejecuciones where id = $1", ejecucion_id
        )
        if fila is None:
            print(f"No existe la ejecución {ejecucion_id}")
            return 1
        defn = obtener(fila["etl"])
        if defn is None:
            print(f"El ETL «{fila['etl']}» no existe en este código (¿versión distinta?)")
            return 1
        params = json.loads(fila["parametros"])
        ctx = Ctx(ejecucion_id, fila["creado_por"])
        for p in defn.parametros:
            if p.tipo != "archivo" or p.nombre not in params:
                continue
            meta = params[p.nombre]
            archivo = await conn.fetchrow(
                "select nombre, contenido from etl_archivos where id = $1", UUID(meta["id"])
            )
            if archivo is None:
                print(
                    f"El archivo «{meta.get('nombre')}» ya no está: se borra al importarlo de "
                    "verdad y a las 24 h de subido. Subilo de nuevo."
                )
                return 1
            destino = carpeta / _nombre_seguro(archivo["nombre"])
            destino.write_bytes(archivo["contenido"])
            params[p.nombre] = destino
            ctx.nombres[p.nombre] = archivo["nombre"]
    finally:
        await conn.close()
    reporte = await defn.ejecutar(params, ctx)
    print(MARCA + json.dumps({"reporte": reporte, "filas": ctx.filas}, default=str), flush=True)
    return 0


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python -m etl.ejecutar <id de la ejecución>")
    carpeta = Path(tempfile.mkdtemp(prefix="etl-"))
    try:
        sys.exit(asyncio.run(_correr(UUID(sys.argv[1]), carpeta)))
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)


if __name__ == "__main__":
    main()
