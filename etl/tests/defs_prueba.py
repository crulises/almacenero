"""ETL de mentira para probar el ejecutor (se cargan con ETL_DEFINICIONES_EXTRA)."""

import asyncio

from etl.registro import Definicion, Param


async def _eco(p, ctx):
    ctx.log("hola desde el ETL")
    ctx.log(f"n={p.get('n')}")
    ctx.filas = 7
    return {"n": 1}


async def _falla(p, ctx):
    ctx.log("antes de romper")
    raise RuntimeError("se rompió a propósito")


async def _dormir(p, ctx):
    ctx.log("durmiendo")
    await asyncio.sleep(60)


async def _archivo(p, ctx):
    ctx.log(f"archivo {ctx.nombres['archivo']}: {p['archivo'].read_text()}")


DEFINICIONES = {
    d.clave: d
    for d in [
        Definicion("t_eco", "Eco", "d", "local", (Param("n", "entero", ayuda="n"),), _eco),
        Definicion("t_eco_web", "Eco web", "d", "web", (), _eco),
        Definicion("t_falla", "Falla", "d", "local", (), _falla),
        Definicion("t_dormir", "Duerme", "d", "local", (), _dormir),
        Definicion(
            "t_archivo",
            "Archivo",
            "d",
            "local",
            (Param("archivo", "archivo", True, "a"), Param("aplicar", "booleano", ayuda="a")),
            _archivo,
            consume_archivo_con="aplicar",
        ),
    ]
}
