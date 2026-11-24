"""Formato `catalogo_curado_v1` del CSV curado (docs/04 §10-B).

CSV UTF-8 con separador `,`. Arriba lleva comentarios `# clave: valor` (formato, generado,
normalizador, fuentes, contenido_sha256) y después la fila de columnas y los datos.

El `sha256` es del **contenido** (la fila de columnas + los datos, con `\\n` y sin BOM), no del
archivo entero: así no cambia con la fecha de `# generado` ni por viajar comprimido o con
`\\r\\n`, y el exportador es reproducible. Si alguien edita el archivo a mano, el hash real
deja de coincidir con el declarado y el importador lo avisa.
"""

import csv
import gzip
import hashlib
import io
import json
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from etl.comun.catalogo import Producto
from etl.comun.ean import normalizar_ean

FORMATO = "catalogo_curado_v1"
COLUMNAS = (
    "ean",
    "nombre",
    "marca",
    "tamano_valor",
    "tamano_unidad",
    "pack_cantidad",
    "presentacion",
    "imagen_url",
    "fuente_origen",
    "nota",
)
UNIDADES = {"g", "kg", "ml", "l", "u"}
MAX_NOMBRE = 200
MAX_MARCA = 100


class FilaInvalida(Exception):
    """La fila no se puede importar. `motivo` es un código estable (sale en el reporte)."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


class FormatoInvalido(ValueError):
    """El archivo entero no es un CSV curado que este importador entienda."""


def _texto(fila: dict[str, str], col: str) -> str:
    return (fila.get(col) or "").strip()


def fila_a_producto(fila: dict[str, str], datos_extra: dict | None = None) -> Producto:
    """Valida una fila y la convierte en `Producto`. Lanza `FilaInvalida`."""
    ean, motivo = normalizar_ean(_texto(fila, "ean"))
    if motivo:
        raise FilaInvalida(motivo)
    nombre = _texto(fila, "nombre")
    if len(nombre) < 2:
        raise FilaInvalida("nombre_corto")
    valor, unidad = _texto(fila, "tamano_valor"), _texto(fila, "tamano_unidad").lower()
    if bool(valor) != bool(unidad):
        raise FilaInvalida("tamano_incompleto")
    tamano_valor = None
    if valor:
        try:
            tamano_valor = Decimal(valor)
        except InvalidOperation:
            raise FilaInvalida("tamano_no_numerico") from None
        if not tamano_valor.is_finite() or tamano_valor <= 0:
            raise FilaInvalida("tamano_no_positivo")
        if unidad not in UNIDADES:
            raise FilaInvalida("unidad_invalida")
    pack = None
    if _texto(fila, "pack_cantidad"):
        try:
            pack = int(_texto(fila, "pack_cantidad"))
        except ValueError:
            raise FilaInvalida("pack_invalido") from None
        if pack < 2:
            raise FilaInvalida("pack_invalido")
    marca = _texto(fila, "marca") or None
    datos = {
        "nombre": nombre,
        "marca": marca,
        "fuente_origen": _texto(fila, "fuente_origen") or None,
        "nota": _texto(fila, "nota") or None,
        **(datos_extra or {}),
    }
    return Producto(
        ean=ean,
        nombre=nombre[:MAX_NOMBRE],
        marca=marca[:MAX_MARCA] if marca else None,
        tamano_valor=tamano_valor,
        tamano_unidad=unidad or None,
        imagen_url=_texto(fila, "imagen_url") or None,
        datos=json.dumps(datos, ensure_ascii=False),
        pack_cantidad=pack,
        presentacion=_texto(fila, "presentacion") or None,
    )


def producto_a_fila(p: Producto, fuente_origen: str, nota: str = "") -> dict[str, str]:
    return {
        "ean": p.ean,
        "nombre": p.nombre,
        "marca": p.marca or "",
        "tamano_valor": format(p.tamano_valor.normalize(), "f") if p.tamano_valor else "",
        "tamano_unidad": p.tamano_unidad or "",
        "pack_cantidad": str(p.pack_cantidad) if p.pack_cantidad else "",
        "presentacion": p.presentacion or "",
        "imagen_url": p.imagen_url or "",
        "fuente_origen": fuente_origen,
        "nota": nota,
    }


def _cuerpo(filas: Iterable[dict[str, str]]) -> str:
    """Columnas + datos, ordenados por EAN, con `\\n`: el contenido que se hashea."""
    salida = io.StringIO()
    w = csv.DictWriter(salida, fieldnames=COLUMNAS, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    for f in sorted(filas, key=lambda f: f["ean"]):
        w.writerow({c: f.get(c, "") for c in COLUMNAS})
    return salida.getvalue()


def _sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def escribir(ruta: Path, filas: Iterable[dict[str, str]], cabecera: dict[str, str]) -> str:
    """Escribe el CSV curado (`.gz` si la ruta lo pide). -> sha256 del contenido."""
    cuerpo = _cuerpo(filas)
    sha = _sha256(cuerpo)
    comentarios = {"formato": FORMATO, **cabecera, "contenido_sha256": sha}
    texto = "".join(f"# {k}: {v}\n" for k, v in comentarios.items()) + cuerpo
    datos = texto.encode("utf-8")
    ruta.write_bytes(gzip.compress(datos, mtime=0) if ruta.suffix == ".gz" else datos)
    return sha


@dataclass
class Lectura:
    cabecera: dict[str, str]
    filas: list[tuple[int, dict[str, str]]]  # (número de línea en el archivo, fila)
    sha256: str  # del contenido tal como está ahora


def leer(ruta: Path) -> Lectura:
    """Lee el CSV curado. Tolera `.gz`, BOM y `\\r\\n`. Lanza `FormatoInvalido`."""
    crudo = ruta.read_bytes()
    if ruta.suffix == ".gz":
        try:
            crudo = gzip.decompress(crudo)
        except (OSError, EOFError) as e:
            raise FormatoInvalido(f"el .gz está roto: {e}") from None
    texto = crudo.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    lineas = texto.split("\n")
    cabecera: dict[str, str] = {}
    i = 0
    while i < len(lineas) and lineas[i].startswith("#"):
        clave, _, valor = lineas[i][1:].partition(":")
        cabecera[clave.strip()] = valor.strip()
        i += 1
    if cabecera.get("formato") != FORMATO:
        raise FormatoInvalido(
            f"falta la cabecera `# formato: {FORMATO}` (el archivo dice "
            f"{cabecera.get('formato')!r}): no es un CSV curado de este proyecto"
        )
    cuerpo = "\n".join(lineas[i:])
    csv.field_size_limit(10**9)
    lector = csv.DictReader(io.StringIO(cuerpo, newline=""))
    if not lector.fieldnames or not {"ean", "nombre"} <= set(lector.fieldnames):
        raise FormatoInvalido("faltan las columnas `ean` y `nombre`")
    filas = []
    fin_anterior = lector.line_num  # línea de las columnas; cada fila empieza en la siguiente
    for f in lector:
        filas.append((i + fin_anterior + 1, {c: (v or "") for c, v in f.items() if c is not None}))
        fin_anterior = lector.line_num
    return Lectura(cabecera, filas, _sha256(cuerpo))
