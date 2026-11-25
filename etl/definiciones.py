# ruff: noqa: E501
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


async def _probar(p: dict, ctx) -> dict:
    from etl.comun.normalizar import Entrada, normalizar
    from etl.comun.reglas_texto import MOTIVOS, TRANSFORMACIONES, base
    from etl.comun.tamano import parsear_tamano

    tam = parsear_tamano(p["tamano"]) if p.get("tamano") else None
    s = normalizar(Entrada(p["nombre"], p.get("marca") or None, tam))
    ctx.log(
        f"Entrada:   nombre={p['nombre']!r} marca={p.get('marca')!r} tamaño={p.get('tamano')!r}"
    )
    t = f"{s.tamano[0].normalize():f} {s.tamano[1]}" if s.tamano else "(sin tamaño)"
    ctx.log(f"Resultado: nombre={s.nombre!r} marca={s.marca!r} tamaño={t} pack={s.pack_cantidad}")
    ctx.log(f"           presentación={s.presentacion!r} fabricante={s.fabricante!r}")
    ctx.log(f"           puntaje {s.calidad} → estado {s.estado}")
    ctx.log("\nReglas que se aplicaron:" if s.transformaciones else "\nNo se aplicó ninguna regla.")
    for id_ in s.transformaciones:
        titulo, que, ejemplo = TRANSFORMACIONES[base(id_)]
        detalle = f" [{id_.split(':', 1)[1]}]" if ":" in id_ else ""
        ctx.log(f"  • {titulo}{detalle}: {que}\n      ej.: {ejemplo}")
    if s.motivos:
        ctx.log("\nMotivos del puntaje:")
        for m in s.motivos:
            ctx.log(f"  • {m}: {MOTIVOS.get(m, '')}")
    return {"nombre": s.nombre, "marca": s.marca, "estado": s.estado, "calidad": s.calidad}


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
    from etl.comun.rutas import ruta_de_salida
    from etl.curado.exportar import exportar

    off = _existe(Path(p["off"])) if p.get("off") else None
    sepa = [_existe(x) for x in _rutas(p.get("sepa", ""))]
    paises = frozenset(x.strip() for x in p.get("paises", "").split(",") if x.strip()) or None
    destino = ruta_de_salida(p["salida"])
    r = await asyncio.to_thread(exportar, destino, off, sepa, paises, p.get("sepa_min_filas", 1))
    ctx.log(f"Escrito {destino}\n{r.texto()}")
    ctx.filas = r.filas
    return {
        "filas": r.filas,
        "sha256": r.sha256,
        "por_origen": dict(r.por_origen),
        "descartadas": dict(r.descartadas),
    }


async def _catalogo_exportar(p: dict, ctx) -> dict:
    from etl.comun.rutas import ruta_de_salida
    from etl.curado.exportar_base import exportar_base

    destino = ruta_de_salida(p["salida"])
    r = await exportar_base(destino)
    ctx.log(f"Escrito {destino}\n{r.texto()}")
    ctx.filas = r.filas
    return {"filas": r.filas, "sha256": r.sha256, "por_origen": dict(r.por_origen)}


async def _locales_exportar(p: dict, ctx) -> dict:
    from etl.comun.rutas import ruta_de_salida
    from etl.locales_intercambio import exportar

    destino = ruta_de_salida(p["salida"])
    r = await exportar(destino, solo_verificados=p.get("solo_verificados", True))
    ctx.log(f"Escrito {destino}\n{r.texto()}")
    ctx.filas = r.filas
    return {"filas": r.filas, "verificados": r.verificados, "sha256": r.sha256}


async def _locales_importar(p: dict, ctx) -> dict:
    from etl.locales_intercambio import importar

    r = await importar(
        p["archivo"], aplicar=p.get("aplicar", False), nombre_archivo=ctx.nombres.get("archivo")
    )
    ctx.log(r.texto())
    ctx.filas = r.leidas
    return {
        "leidas": r.leidas,
        "nuevos": r.nuevos,
        "existentes": r.existentes,
        "verificados_ahora": r.verificados_ahora,
        "vinculos_nuevos": r.vinculos_nuevos,
        "invalidas": dict(r.invalidas),
        "sha256": r.sha256,
    }


async def _eventos_exportar(p: dict, ctx) -> dict:
    from etl.eventos_exportar import exportar

    return await exportar(p, ctx)


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
            "Importa un export de catálogo (catalogo_curado_v1 o v2, en .zip, .csv.gz o .csv) al catálogo. Primero subilo y corré el "
            "simulacro; si el reporte está bien, repetí con «aplicar». El archivo se borra al "
            "importar de verdad (o a las 24 h); queda su hash en el lote.",
            "web",
            (
                Param(
                    "archivo",
                    "archivo",
                    True,
                    "El .zip del export (sirve también .csv o .csv.gz). Hasta 25 MB.",
                ),
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
            "normalizador_probar",
            "Probar el normalizador con un producto",
            "Escribí un nombre (y opcionalmente marca y tamaño) tal como lo diría una fuente y mirá "
            "qué hace el normalizador paso a paso: qué reglas aplica, qué queda y qué puntaje saca. "
            "No toca la base.",
            "web",
            (
                Param(
                    "nombre", "texto", True, "Nombre crudo, p. ej. ACEITE GIRASOL COCINERO 900 CC."
                ),
                Param(
                    "marca",
                    "texto",
                    ayuda="Marca que traería la fuente (opcional), p. ej. COCINERO.",
                ),
                Param(
                    "tamano",
                    "texto",
                    ayuda="Tamaño que traería el campo de la fuente (opcional), p. ej. 900 ml.",
                ),
            ),
            _probar,
        ),
        Definicion(
            "catalogo_renormalizar",
            "Renormalizar el catálogo",
            "Pasa el normalizador por todo el catálogo, actualiza lo que difiera y recalcula la "
            "calidad (Doc 7). Hace falta al cambiar la versión del normalizador o un diccionario. "
            "El log dice qué reglas se aplicaron, a cuántos productos y con qué ejemplos. Sin "
            "«aplicar» es un simulacro.",
            "web",
            (_APLICAR,),
            _renormalizar,
        ),
        Definicion(
            "catalogo_calidad",
            "Medir la calidad del catálogo",
            "Mide el catálogo actual con el normalizador, sin escribir nada: estados, qué reglas "
            "aplicaría y por qué los productos bajan de puntaje. Si «cambiaría» da 0, el catálogo ya "
            "está normalizado. Los parámetros solo cambian la lista de ejemplos del final.",
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
                    ayuda="Listar ejemplos solo de este estado (no afecta el resumen, que es del catálogo entero).",
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
            "Arma el catálogo curado desde OFF y SEPA de la máquina del worker (no toca la base). "
            "Deja un .zip con el CSV y un LEEME.txt que cuenta qué reglas del normalizador se aplicaron.",
            "local",
            (
                Param(
                    "salida",
                    "nombre_archivo",
                    True,
                    "Solo un nombre, sin extensión ni carpeta. Se guarda como .zip (datos + "
                    "LEEME.txt) en la carpeta de exports del worker (ETL_EXPORT_DIR).",
                    "catalogo-curado",
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
        Definicion(
            "catalogo_exportar",
            "Exportar el catálogo (formato de intercambio)",
            "Vuelca el catálogo de la base al formato catalogo_curado_v2: los datos de cada "
            "producto más sus metadatos (origen, campos bloqueados, si lo cargó o revisó una "
            "persona, sugerencias, avisos del normalizador, conflictos). Deja un .zip con el CSV "
            "y un LEEME.txt que explica qué se hizo. Se puede importar acá o en otro proyecto sin "
            "perder ese trabajo. Ver docs/09.",
            "local",
            (
                Param(
                    "salida",
                    "nombre_archivo",
                    True,
                    "Solo un nombre, sin extensión ni carpeta. Se guarda como .zip (datos + "
                    "LEEME.txt) en la carpeta de exports del worker (ETL_EXPORT_DIR).",
                    "catalogo-intercambio",
                ),
            ),
            _catalogo_exportar,
        ),
        Definicion(
            "locales_exportar",
            "Exportar locales (formato de intercambio)",
            "Vuelca los locales verificados a un .zip (CSV + LEEME.txt) para llevarlos a otra "
            "instalación sin el modo migración. Lleva nombre, dirección, ubicación, fuente, "
            "vínculos con OSM/SEPA, medios de pago y recargo; no lleva personas. Ver docs/09 §8.",
            "local",
            (
                Param(
                    "salida",
                    "nombre_archivo",
                    True,
                    "Solo un nombre, sin extensión ni carpeta. Se guarda como .zip en la carpeta "
                    "de exports del worker (ETL_EXPORT_DIR).",
                    "locales-intercambio",
                ),
                Param(
                    "solo_verificados",
                    "booleano",
                    default=True,
                    ayuda="Solo los locales que un admin ya verificó. Destildalo para llevarlos todos.",
                ),
            ),
            _locales_exportar,
        ),
        Definicion(
            "locales_importar",
            "Importar locales (formato de intercambio)",
            "Suma a esta base los locales de un export de locales. Los que ya existen (mismo "
            "vínculo OSM/SEPA o mismo nombre a pocos metros) no se pisan: solo se verifican si el "
            "archivo los trae verificados. Primero el simulacro; si está bien, repetí con «aplicar».",
            "web",
            (
                Param(
                    "archivo",
                    "archivo",
                    True,
                    "El .zip del export (sirve también .csv). Hasta 25 MB.",
                ),
                _APLICAR,
            ),
            _locales_importar,
            consume_archivo_con="aplicar",
        ),
        Definicion(
            "eventos_exportar",
            "Exportar eventos al almacén",
            "Saca los eventos de la app (escaneos, aperturas…) a uno o más .zip (eventos.csv + "
            "LEEME.txt) en el almacén de exportaciones (S3 o disco, ver docs/04 §11.4). Con «borrar» "
            "los vacía de la base, pero solo después de volver a leer cada archivo y comprobar "
            "tamaño y sha256; si algo falla, no se borra nada. Lleva ids de usuario: es para análisis "
            "interno.",
            "web",
            (
                Param(
                    "tipo",
                    "texto",
                    ayuda="Solo ese tipo de evento (p. ej. producto.escaneado). Vacío: todos.",
                ),
                Param(
                    "hasta",
                    "fecha",
                    ayuda="Solo los eventos hasta el fin de ese día (UTC). Vacío: hasta ahora.",
                ),
                Param(
                    "borrar",
                    "booleano",
                    default=False,
                    ayuda="Borra de la base los eventos ya exportados y verificados. Sin marcar, "
                    "solo exporta.",
                ),
            ),
            _eventos_exportar,
        ),
    ]
}
