"""Texto del `LEEME.txt` que viaja dentro del `.zip` de un export de catálogo: qué es el archivo,
de dónde salió, qué reglas del normalizador se aplicaron (con cuántos productos y un ejemplo) y
cómo volver a importarlo. Pensado para quien lo recibe y no estuvo en la conversación."""

from collections import Counter

from etl.comun.normalizar import NORMALIZADOR_VERSION
from etl.comun.resumen import Trazas, explicar_motivos
from etl.curado.formato import COLUMNAS, COLUMNAS_META, FORMATO, FORMATO_V2

_QUE_ES = {
    FORMATO: (
        "Catálogo de productos curado (formato catalogo_curado_v1): los datos de cada producto "
        "(EAN, nombre, marca, tamaño, presentación, imagen) ya pasados por el normalizador."
    ),
    FORMATO_V2: (
        "Catálogo de productos con metadatos de tratamiento (formato catalogo_curado_v2): los "
        "datos de cada producto y, además, qué se hizo con él (de dónde viene, qué campos "
        "bloqueó una persona, si se cargó o revisó a mano, sugerencias, avisos, conflictos)."
    ),
}

_COMO_IMPORTAR = (
    "Panel de admin: ETL → «Importar CSV curado», elegí este .zip (sin descomprimir) y\n"
    "corré primero el simulacro; si el reporte está bien, repetí con «aplicar».\n"
    "Por consola: make catalogo-csv-importar ARCHIVO=<este .zip> [APLICAR=1]\n"
    "El importador reconoce el formato por el contenido. Detalle del formato: docs/09 del repo."
)


def seccion_que_es(formato: str, filas: int, por_origen: Counter, cabecera: dict[str, str]) -> str:
    lineas = [
        _QUE_ES[formato],
        "",
        f"Filas (productos): {filas}",
        f"Generado:          {cabecera.get('generado', '-')}",
        f"Normalizador:      versión {cabecera.get('normalizador', NORMALIZADOR_VERSION)}",
        f"Fuentes:           {cabecera.get('fuentes', '-')}",
    ]
    if por_origen:
        lineas += ["", "Productos por origen:"]
        lineas += [f"  {o}: {n}" for o, n in por_origen.most_common()]
    return "\n".join(lineas)


def seccion_reglas(trazas: Trazas, total: int, antes_de: str) -> str:
    """`antes_de`: qué se normalizó, para que el texto diga de dónde salen los números."""
    return (
        f"El normalizador (versión {NORMALIZADOR_VERSION}) corrió sobre {antes_de}.\n\n"
        + trazas.texto(total)
    )


def seccion_motivos(motivos: Counter, total: int) -> str:
    if not motivos:
        return "Ningún producto tiene motivos que le resten puntaje."
    return (
        "Por qué algunos productos no llegan al puntaje máximo (cada producto puede sumar "
        "varios motivos):\n" + explicar_motivos(motivos, total)
    )


def seccion_columnas(formato: str) -> str:
    cols = COLUMNAS + (COLUMNAS_META if formato == FORMATO_V2 else ())
    return (
        "Dentro del .zip hay un CSV UTF-8 separado por comas. Arriba tiene comentarios `# clave:"
        " valor` (formato, generado, normalizador, fuentes, contenido_sha256) y después la fila"
        " de columnas:\n  " + ", ".join(cols) + "\nLas listas (campos bloqueados, motivos) van"
        " separadas por `|`. Los metadatos son conteos y banderas: no llevan ids de personas."
    )


def seccion_importar() -> str:
    return _COMO_IMPORTAR
