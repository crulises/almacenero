"""El «paquete» de un export: un `.zip` con los datos (CSV) y un `LEEME.txt` que cuenta qué es,
cómo se armó y qué reglas se aplicaron. Y la lectura inversa: dado un archivo cualquiera, sacar
el CSV de adentro, sea un `.zip` (paquete), un `.gz` o un CSV pelado. El formato se reconoce por
el **contenido** (los primeros bytes), no por la extensión: quien sube el archivo no tiene que
acordarse de cómo se llamaba.
"""

import gzip
import io
import zipfile
from collections.abc import Callable
from pathlib import Path

MAX_DESCOMPRIMIDO = 2 * 1024**3  # tope contra «bombas» de compresión
LEEME = "LEEME.txt"
_FECHA_FIJA = (2020, 1, 1, 0, 0, 0)  # mismo contenido -> mismo zip (reproducible)


class PaqueteInvalido(ValueError):
    pass


def escribir_zip(ruta: Path, nombre_csv: str, datos: bytes, leeme: str | None) -> None:
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        if leeme:
            info = zipfile.ZipInfo(LEEME, _FECHA_FIJA)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, leeme.encode("utf-8"))
        info = zipfile.ZipInfo(nombre_csv, _FECHA_FIJA)
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, datos, compresslevel=6)


def contenido_csv(crudo: bytes) -> bytes:
    """Los bytes del CSV, venga como venga. Lanza `PaqueteInvalido`."""
    if crudo[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(crudo)) as z:
                csvs = [
                    i
                    for i in z.infolist()
                    if not i.is_dir() and i.filename.lower().endswith(".csv")
                ]
                if not csvs:
                    raise PaqueteInvalido("el .zip no tiene ningún archivo .csv adentro")
                if len(csvs) > 1:
                    nombres = ", ".join(i.filename for i in csvs)
                    raise PaqueteInvalido(
                        f"el .zip tiene {len(csvs)} archivos .csv ({nombres}): tiene que haber uno"
                    )
                if csvs[0].file_size > MAX_DESCOMPRIMIDO:
                    raise PaqueteInvalido("el .csv de adentro es demasiado grande")
                with z.open(csvs[0]) as f:
                    datos = f.read(MAX_DESCOMPRIMIDO + 1)
        except zipfile.BadZipFile as e:
            raise PaqueteInvalido(f"el .zip está roto: {e}") from None
    elif crudo[:2] == b"\x1f\x8b":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(crudo)) as f:
                datos = f.read(MAX_DESCOMPRIMIDO + 1)
        except (OSError, EOFError) as e:
            raise PaqueteInvalido(f"el .gz está roto: {e}") from None
    else:
        datos = crudo
    if len(datos) > MAX_DESCOMPRIMIDO:
        raise PaqueteInvalido("el contenido descomprimido es demasiado grande")
    return datos


def leeme_de(titulo: str, secciones: list[tuple[str, str]]) -> Callable[[str], str]:
    """Arma el `LEEME.txt` a partir de secciones (título, texto). Devuelve una función que
    recibe el sha256 del contenido (que recién se conoce al escribir) y lo agrega arriba."""

    def armar(sha256: str) -> str:
        partes = [titulo, "=" * len(titulo), "", f"sha256 del contenido: {sha256}", ""]
        for t, cuerpo in secciones:
            partes += [t, "-" * len(t), cuerpo.rstrip(), ""]
        return "\n".join(partes)

    return armar
