"""Worker local de ETL: `make etl-worker`. Toma de la cola de la base (local o remota, la de
`DATABASE_URL`) lo que el panel marcó como `local` y lo corre con los archivos de esta máquina.
Conexión saliente solamente: no abre puertos. Ctrl-C lo detiene (termina la vuelta en curso)."""

import asyncio
import signal

from etl.comun.catalogo import database_url
from etl.ejecucion import bucle


async def main() -> None:
    parar = asyncio.Event()
    loop = asyncio.get_running_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(s, parar.set)
    print("[etl] worker local esperando trabajo (Ctrl-C para salir)", flush=True)
    await bucle(database_url(), "local", parar, max_s=6 * 3600)
    print("[etl] worker detenido", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
