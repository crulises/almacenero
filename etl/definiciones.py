"""Las definiciones de cada ETL que se puede disparar desde el panel (docs/04 §10-A).

Cada `ejecutar(parametros, ctx)` llama al mismo código que corren los `make etl-*` de siempre.
Los imports son perezosos: pedir la lista de definiciones (para dibujar el formulario) no carga
`pyosmium` ni nada pesado. `ctx.log(texto)` escribe en el log de la ejecución.
"""

import asyncio
import dataclasses
from collections import Counter
from pathlib import Path
from typing import Any

from etl.registro import Definicion, Param

OFF_PAISES = "en:argentina,en:paraguay,en:brazil,en:chile,en:uruguay,en:bolivia"


def a_dict(obj: Any) -> dict[str, Any]:
    """Reporte (dataclass con Counter, Decimal, UUID…) -> JSON plano."""

    def plano(v: Any) -> Any:
        if isinstance(v, Counter | dict):
            return {str(k): plano(x) for k, x in v.items()}
        if isinstance(v, list | tuple):
            return [plano(x) for x in v]
        if isinstance(v, int | float | bool | str) or v is None:
            return v
        return str(v)

    if dataclasses.is_dataclass(obj):
        return {f.name: plano(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    return {"resultado": plano(obj)}


def _rutas(texto: str) -> list[Path]:
    return [Path(r) for r in texto.split()]


def _existe(ruta: Path) -> Path:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe {ruta} en la máquina donde corre el ETL")
    return ruta


async def _curado_importar(p: dict, ctx) -> dict:
    from etl.curado.importar import importar

    r = await importar(
        p["archivo"],
        aplicar=p.get("aplicar", False),
        forzar=p.get("forzar", False),
        subido_por=ctx.usuario_id,
        etl_ejecucion_id=ctx.ejecucion_id,
        nombre_archivo=ctx.nombres.get("archivo"),
    )
    ctx.log(r.texto())
    ctx.filas = r.leidas
    return {**a_dict(r), "fusion": a_dict(r.fusion)}


async def _renormalizar(p: dict, ctx) -> dict:
    from etl.renormalizar import renormalizar

    texto = await renormalizar(p.get("aplicar", False))
    ctx.log(texto)
    return {"resumen": texto}


async def _calidad(p: dict, ctx) -> dict:
    from etl.calidad import medir

    texto = await medir(p.get("muestra", 0), p.get("estado"))
    ctx.log(texto)
    return {"resumen": texto}


async def _off(p: dict, ctx) -> dict:
    from etl.off.__main__ import cargar

    paises = frozenset(x.strip() for x in p.get("paises", "").split(",") if x.strip()) or None
    r = await cargar(_existe(Path(p["archivo"])), limite=p.get("limite"), paises=paises)
    ctx.log(r.texto())
    ctx.filas = r.leidas
    return a_dict(r)


async def _sepa(p: dict, ctx) -> dict:
    from etl.sepa.__main__ import cargar

    r = await cargar([_existe(x) for x in _rutas(p["archivos"])])
    ctx.log(r.texto())
    ctx.filas = r.leidas
    return a_dict(r)


async def _sepa_locales(p: dict, ctx) -> dict:
    from etl.sepa.locales import cargar

    r = await cargar([_existe(x) for x in _rutas(p["archivos"])], p.get("provincia") or None)
    ctx.log(r.texto())
    return a_dict(r)


async def _osm(p: dict, ctx) -> dict:
    from etl.osm.__main__ import cargar

    r = await cargar(_existe(Path(p["archivo"])), p["provincia"])
    ctx.log(r.texto())
    return a_dict(r)


async def _curado_exportar(p: dict, ctx) -> dict:
    from etl.curado.exportar import exportar

    off = _existe(Path(p["off"])) if p.get("off") else None
    sepa = [_existe(x) for x in _rutas(p.get("sepa", ""))]
    paises = frozenset(x.strip() for x in p.get("paises", "").split(",") if x.strip()) or None
    r = await asyncio.to_thread(
        exportar, Path(p["salida"]), off, sepa, paises, p.get("sepa_min_filas", 1)
    )
    ctx.log(f"Escrito {p['salida']}\n{r.texto()}")
    ctx.filas = r.filas
    return {
        "filas": r.filas,
        "sha256": r.sha256,
        "por_origen": dict(r.por_origen),
        "descartadas": dict(r.descartadas),
    }


_APLICAR = Param(
    "aplicar",
    "booleano",
    default=False,
    ayuda="Sin marcar es un simulacro: corre todo y muestra el reporte, pero no escribe nada.",
)

DEFINICIONES: dict[str, Definicion] = {
    d.clave: d
    for d in [
        Definicion(
            "curado_importar",
            "Importar CSV curado",
            "Importa un CSV curado (catalogo_curado_v1) al catálogo. Primero subilo y corré el "
            "simulacro; si el reporte está bien, repetí con «aplicar». El archivo se borra al "
            "importar de verdad (o a las 24 h); queda su hash en el lote.",
            "web",
            (
                Param("archivo", "archivo", True, "El CSV curado (.csv o .csv.gz, hasta 25 MB)."),
                _APLICAR,
                Param(
                    "forzar",
                    "booleano",
                    default=False,
                    ayuda="Importar aunque este mismo archivo ya se haya importado.",
                ),
            ),
            _curado_importar,
            consume_archivo_con="aplicar",
        ),
        Definicion(
            "catalogo_renormalizar",
            "Renormalizar el catálogo",
            "Pasa el normalizador por todo el catálogo y recalcula la calidad (Doc 7). Hace falta "
            "al cambiar la versión del normalizador o un diccionario.",
            "web",
            (_APLICAR,),
            _renormalizar,
        ),
        Definicion(
            "catalogo_calidad",
            "Medir la calidad del catálogo",
            "Corre el normalizador sin escribir nada y muestra cómo quedaría el catálogo.",
            "web",
            (
                Param(
                    "muestra",
                    "entero",
                    ayuda="Cuántos ejemplos de antes/después mostrar.",
                    default=0,
                ),
                Param(
                    "estado",
                    "opcion",
                    ayuda="Mostrar ejemplos solo de este estado.",
                    opciones=("completo", "parcial", "dudoso", "descartado"),
                ),
            ),
            _calidad,
        ),
        Definicion(
            "off",
            "Cargar Open Food Facts",
            "Lee un volcado CSV de OFF que ya esté en la máquina del worker y lo fusiona.",
            "local",
            (
                Param(
                    "archivo",
                    "texto",
                    True,
                    "Ruta del volcado en la máquina del worker.",
                    "etl/data/off.csv.gz",
                ),
                Param(
                    "paises",
                    "texto",
                    ayuda="Tags de OFF separados por coma; vacío = todo el mundo.",
                    default=OFF_PAISES,
                ),
                Param(
                    "limite", "entero", ayuda="Procesar solo las primeras N filas (para probar)."
                ),
            ),
            _off,
        ),
        Definicion(
            "sepa",
            "Cargar SEPA (catálogo)",
            "Lee uno o más zips diarios de SEPA de la máquina del worker y fusiona los productos.",
            "local",
            (
                Param(
                    "archivos",
                    "texto",
                    True,
                    "Rutas de los zips en la máquina del worker, separadas por espacio.",
                ),
            ),
            _sepa,
        ),
        Definicion(
            "sepa_locales",
            "Cargar sucursales de SEPA como locales",
            "Crea locales (sin verificar) desde las sucursales de SEPA.",
            "local",
            (
                Param(
                    "archivos",
                    "texto",
                    True,
                    "Rutas de los zips en la máquina del worker, separadas por espacio.",
                ),
                Param(
                    "provincia",
                    "texto",
                    ayuda="Slug o código AR-N (misiones, caba…); vacío = todo el país.",
                ),
            ),
            _sepa_locales,
        ),
        Definicion(
            "osm",
            "Cargar locales de OpenStreetMap",
            "Supermercados y almacenes de un extracto de Geofabrik, de una provincia.",
            "local",
            (
                Param(
                    "archivo",
                    "texto",
                    True,
                    "Extracto .osm.pbf en la máquina del worker.",
                    "etl/data/osm/argentina-latest.osm.pbf",
                ),
                Param("provincia", "texto", True, "Slug o código AR-N (misiones, caba…)."),
            ),
            _osm,
        ),
        Definicion(
            "curado_exportar",
            "Armar el CSV curado",
            "Arma el CSV curado desde OFF y SEPA de la máquina del worker (no toca la base).",
            "local",
            (
                Param(
                    "salida",
                    "texto",
                    True,
                    "Dónde escribir el CSV curado.",
                    "etl/data/catalogo-curado.csv.gz",
                ),
                Param("off", "texto", ayuda="Volcado de OFF (opcional)."),
                Param("sepa", "texto", ayuda="Zips de SEPA separados por espacio (opcional)."),
                Param(
                    "paises",
                    "texto",
                    ayuda="Tags de OFF separados por coma; vacío = todos.",
                    default=OFF_PAISES,
                ),
                Param(
                    "sepa_min_filas",
                    "entero",
                    ayuda="Descartar EAN de SEPA con menos filas que esto.",
                    default=1,
                ),
            ),
            _curado_exportar,
        ),
    ]
}
