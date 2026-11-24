"""Medidor de calidad del catálogo (Doc 7): corre el normalizador sobre `productos_canonicos`
SIN escribir nada y muestra cómo quedaría (antes -> después).

    python -m etl.calidad [--muestra N] [--estado dudoso] [--semilla S]
"""

import argparse
import asyncio
import random
from collections import Counter
from decimal import Decimal

from etl.comun.catalogo import conectar
from etl.comun.normalizar import NORMALIZADOR_VERSION, Entrada, Salida, normalizar
from etl.comun.reglas_texto import ESTADOS, reglas_en_orden
from etl.comun.resumen import Trazas, explicar_motivos


async def medir(muestra: int, estado: str | None, prefijo_ean: str | None = None) -> str:
    """`prefijo_ean`: solo para tests (medir un subconjunto)."""
    conn = await conectar()
    total = cambian = 0
    estados: Counter = Counter()
    motivos: Counter = Counter()
    antes: Counter = Counter()
    despues: Counter = Counter()
    marcas_antes: set[str] = set()
    marcas_despues: set[str] = set()
    trazas = Trazas()
    ejemplos: list[tuple[dict, Salida]] = []
    elegibles = 0
    rng = random.Random(7)
    try:
        async with conn.transaction():
            cur = conn.cursor(
                "select nombre, marca, tamano_valor, tamano_unidad, imagen_url "
                "from productos_canonicos where ($1::text is null or ean like $1 || '%')",
                prefijo_ean,
            )
            async for r in cur:
                total += 1
                tam = (
                    (Decimal(r["tamano_valor"]), r["tamano_unidad"]) if r["tamano_valor"] else None
                )
                s = normalizar(Entrada(r["nombre"], r["marca"], tam, bool(r["imagen_url"])))
                estados[s.estado] += 1
                motivos.update(s.motivos)
                cambian += r["nombre"] != s.nombre
                trazas.agregar(s, r["nombre"], s.nombre)
                antes["sin_tamano"] += tam is None
                despues["sin_tamano"] += s.tamano is None
                antes["sin_marca"] += not r["marca"]
                despues["sin_marca"] += s.marca is None
                if r["marca"]:
                    marcas_antes.add(r["marca"])
                if s.marca:
                    marcas_despues.add(s.marca)
                if muestra and (estado is None or s.estado == estado):
                    elegibles += 1
                    if len(ejemplos) < muestra:
                        ejemplos.append((dict(r), s))
                    elif rng.random() < muestra / elegibles:
                        ejemplos[rng.randrange(muestra)] = (dict(r), s)
    finally:
        await conn.close()

    def pct(n: int) -> str:
        return f"{n:>7}  {100 * n / max(total, 1):5.1f} %"

    out = [
        f"CALIDAD DEL CATÁLOGO (normalizador v{NORMALIZADOR_VERSION}) — solo mide, no escribe nada",
        "",
        "Cómo leerlo: toma cada producto del catálogo ACTUAL, le pasa el normalizador y cuenta",
        "qué pasaría. Si «cambiaría» da 0, el catálogo ya está normalizado con estas reglas (lo",
        "normal después de renormalizar): por eso los ejemplos «antes → después» salen vacíos.",
        "Los parámetros solo cambian la lista de EJEMPLOS del final (muestra = cuántos, estado =",
        "de qué estado). Todo lo demás es siempre del catálogo completo.",
        "",
        f"Productos: {total}",
        f"Productos que el normalizador cambiaría hoy: {cambian}",
        "",
        "Estado (según el normalizador):",
    ]
    out += [f"  {e:<11}{pct(estados[e])}  {ESTADOS[e]}" for e in ESTADOS]
    out += ["", "                antes     después"]
    out.append(f"  sin tamaño   {antes['sin_tamano']:>7}  {despues['sin_tamano']:>7}")
    out.append(f"  sin marca    {antes['sin_marca']:>7}  {despues['sin_marca']:>7}")
    out.append(f"  marcas dist. {len(marcas_antes):>7}  {len(marcas_despues):>7}")
    out += ["", trazas.texto(total)]
    out += ["", "Por qué los productos bajan de puntaje:", explicar_motivos(motivos, total)]
    out.append("")
    if not muestra:
        out.append("Ejemplos: no pediste ninguno (poné un número en «muestra»).")
    else:
        filtro = f", estado {estado}" if estado else ""
        out.append(f"Ejemplos al azar ({len(ejemplos)} de {elegibles} que cumplen{filtro}):")
        for r, s in ejemplos:
            tam = f"{s.tamano[0].normalize():f} {s.tamano[1]}" if s.tamano else "sin tamaño"
            out.append(f"  {r['nombre']!r} [{r['marca']}]")
            if r["nombre"] != s.nombre:
                out.append(f"    el normalizador lo dejaría: {s.nombre!r} [{s.marca}] {tam}")
            out.append(
                f"    puntaje {s.calidad} ({s.estado}); motivos: {', '.join(s.motivos) or '-'}"
            )
    out += ["", "Reglas que aplica el normalizador, en orden:", reglas_en_orden()]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--muestra", type=int, default=0, help="cuántos ejemplos mostrar")
    ap.add_argument("--estado", choices=["completo", "parcial", "dudoso", "descartado"])
    args = ap.parse_args()
    print(asyncio.run(medir(args.muestra, args.estado)))


if __name__ == "__main__":
    main()
