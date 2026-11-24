"""Dónde escriben sus archivos los ETL: la carpeta la decidimos nosotros, no quien llena el form.

A los exports se les pide solo un **nombre** (`catalogo-2026-11`): ni carpeta ni extensión. La
carpeta base es `ETL_EXPORT_DIR` (por defecto `etl/data/exports/`, que está en .gitignore) y el
formato del archivo lo decide el export: un `.zip` con los datos y un `LEEME.txt` adentro. Si
alguien escribe igual `.zip`, `.csv` o `.csv.gz`, se ignora (no hace falta saber de formatos).
"""

import os
import re
from pathlib import Path

DIR_POR_DEFECTO = Path("etl/data/exports")
EXTENSIONES_CONOCIDAS = (".csv.gz", ".zip", ".csv", ".gz")
_NOMBRE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class NombreInvalido(ValueError):
    pass


def dir_exports() -> Path:
    return Path(os.environ.get("ETL_EXPORT_DIR") or DIR_POR_DEFECTO)


def validar_nombre(nombre: str) -> str:
    """-> el nombre sin extensión de formato. Solo un nombre: sin carpetas ni `..`."""
    nombre = (nombre or "").strip()
    for ext in EXTENSIONES_CONOCIDAS:
        if nombre.lower().endswith(ext) and len(nombre) > len(ext):
            nombre = nombre[: -len(ext)]
            break
    if not _NOMBRE.match(nombre) or ".." in nombre or nombre.endswith("."):
        raise NombreInvalido(
            "poné solo un nombre (letras, números, punto, guion), sin carpetas ni espacios"
        )
    return nombre


def ruta_de_salida(nombre: str, extension: str = ".zip") -> Path:
    """-> `<carpeta de exports>/<nombre><extension>`, creando la carpeta.
    Lanza `NombreInvalido`. Si ya existe un archivo con ese nombre, se reemplaza."""
    base = dir_exports()
    base.mkdir(parents=True, exist_ok=True)
    return base / (validar_nombre(nombre) + extension)
