"""Dónde escriben sus archivos los ETL: la carpeta la decidimos nosotros, no quien llena el form.

A los exports se les pide solo un **nombre de archivo** (`catalogo-curado.csv.gz`); la carpeta
base es `ETL_EXPORT_DIR` (por defecto `etl/data/exports/`, que está en .gitignore). Así un
formulario del panel no puede escribir en cualquier lado de la máquina del worker.
"""

import os
import re
from pathlib import Path

DIR_POR_DEFECTO = Path("etl/data/exports")
EXTENSIONES = (".csv", ".csv.gz")
_NOMBRE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class NombreInvalido(ValueError):
    pass


def dir_exports() -> Path:
    return Path(os.environ.get("ETL_EXPORT_DIR") or DIR_POR_DEFECTO)


def validar_nombre(nombre: str) -> str:
    """Solo un nombre: sin carpetas, sin `..`, con extensión .csv o .csv.gz."""
    nombre = (nombre or "").strip()
    if not _NOMBRE.match(nombre) or ".." in nombre:
        raise NombreInvalido(
            "poné solo el nombre del archivo (letras, números, punto, guion), sin carpetas"
        )
    if not nombre.endswith(EXTENSIONES):
        raise NombreInvalido("el archivo tiene que terminar en .csv o .csv.gz")
    return nombre


def ruta_de_salida(nombre: str) -> Path:
    """-> `<carpeta de exports>/<nombre>`, creando la carpeta. Lanza `NombreInvalido`."""
    base = dir_exports()
    base.mkdir(parents=True, exist_ok=True)
    return base / validar_nombre(nombre)
