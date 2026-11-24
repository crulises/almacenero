"""Formatos `catalogo_curado_v1` y `catalogo_curado_v2` del CSV curado (docs/04 §10-B, docs/09).

v1 (lo que arma `make catalogo-csv-exportar` desde las fuentes crudas) trae solo los datos del
producto. v2 (lo que arma `make catalogo-csv-exportar-base` desde la base) suma los **metadatos
del tratamiento** de cada producto: de dónde viene, qué campos tiene bloqueados, si lo cargó o
corrigió una persona, sugerencias, avisos del normalizador, conflictos. El importador lee los dos.

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
FORMATO_V2 = "catalogo_curado_v2"
FORMATOS = (FORMATO, FORMATO_V2)
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
# Metadatos de v2. Se **restauran** al importar: origen, campos_bloqueados. El resto es
# informativo (queda en `producto_fuentes.datos.intercambio`): la calidad la recalcula siempre el
# normalizador de quien importa, no se confía en la de otro proyecto.
COLUMNAS_META = (
    "origen",
    "campos_bloqueados",
    "calidad",
    "estado_calidad",
    "calidad_motivos",
    "normalizador_version",
    "cargado_a_mano",
    "revisado",
    "ediciones_admin",
    "sugerencias_aprobadas",
    "sugerencias_rechazadas",
    "sugerencias_pendientes",
    "avisos_normalizador",
    "conflictos_resueltos",
    "conflictos_pendientes",
)
COLUMNAS_V2 = COLUMNAS + COLUMNAS_META
COLUMNAS_DE = {FORMATO: COLUMNAS, FORMATO_V2: COLUMNAS_V2}
ORIGENES = {"off", "sepa", "curado", "manual"}
BLOQUEABLES = {"nombre", "marca", "tamano", "presentacion"}
SEP_LISTA = "|"  # separador dentro de una celda (campos_bloqueados, calidad_motivos)
_CONTADORES = (
    "ediciones_admin",
    "sugerencias_aprobadas",
    "sugerencias_rechazadas",
    "sugerencias_pendientes",
    "avisos_normalizador",
    "conflictos_resueltos",
    "conflictos_pendientes",
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


def _ean_de_catalogo(crudo: str) -> str | None:
    """EAN que una persona ya aceptó en el catálogo (origen manual): solo se exige el largo."""
    return crudo if crudo.isdigit() and 8 <= len(crudo) <= 14 else None


def fila_a_producto(
    fila: dict[str, str], datos_extra: dict | None = None, ean_confiable: bool = False
) -> Producto:
    """Valida una fila y la convierte en `Producto`. Lanza `FilaInvalida`.

    `ean_confiable`: la fila es de un producto cargado a mano (v2, `origen = manual`) y el catálogo
    de origen ya lo aceptó; se le perdona el dígito verificador para que el intercambio sea fiel."""
    ean, motivo = normalizar_ean(_texto(fila, "ean"))
    if motivo == "ean_digito_verificador" and ean_confiable:
        ean, motivo = _ean_de_catalogo(_texto(fila, "ean")), None
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


@dataclass(frozen=True)
class Meta:
    """Lo que el v2 dice del tratamiento de un producto. `bloqueados` y `origen` se restauran."""

    origen: str | None
    bloqueados: tuple[str, ...]
    info: dict  # el resto, tal cual (informativo)

    @property
    def hay_trabajo_humano(self) -> bool:
        return self.origen == "manual" or bool(self.bloqueados)


def meta_de_fila(fila: dict[str, str]) -> Meta | None:
    """Los metadatos v2 de una fila, validados. `None` si la fila no los trae (v1).
    Lanza `FilaInvalida` (`origen_invalido`, `bloqueo_invalido`, `meta_invalida`)."""
    if "origen" not in fila:
        return None
    origen = _texto(fila, "origen") or None
    if origen is not None and origen not in ORIGENES:
        raise FilaInvalida("origen_invalido")
    bloqueados = tuple(sorted({x for x in _texto(fila, "campos_bloqueados").split(SEP_LISTA) if x}))
    if not set(bloqueados) <= BLOQUEABLES:
        raise FilaInvalida("bloqueo_invalido")
    info: dict = {}
    for c in _CONTADORES:
        v = _texto(fila, c)
        if not v:
            continue
        if not v.isdigit():
            raise FilaInvalida("meta_invalida")
        info[c] = int(v)
    for c in ("cargado_a_mano", "revisado"):
        v = _texto(fila, c)
        if v not in ("", "0", "1"):
            raise FilaInvalida("meta_invalida")
        if v:
            info[c] = v == "1"
    for c in ("calidad", "normalizador_version"):
        v = _texto(fila, c)
        if v and not v.isdigit():
            raise FilaInvalida("meta_invalida")
        if v:
            info[c] = int(v)
    if _texto(fila, "estado_calidad"):
        info["estado_calidad"] = _texto(fila, "estado_calidad")
    motivos = [x for x in _texto(fila, "calidad_motivos").split(SEP_LISTA) if x]
    if motivos:
        info["calidad_motivos"] = motivos
    return Meta(origen, bloqueados, info)


def _cuerpo(filas: Iterable[dict[str, str]], columnas: tuple[str, ...] = COLUMNAS) -> str:
    """Columnas + datos, ordenados por EAN, con `\\n`: el contenido que se hashea."""
    salida = io.StringIO()
    w = csv.DictWriter(salida, fieldnames=columnas, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    for f in sorted(filas, key=lambda f: f["ean"]):
        w.writerow({c: f.get(c, "") for c in columnas})
    return salida.getvalue()


def _sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def escribir(
    ruta: Path, filas: Iterable[dict[str, str]], cabecera: dict[str, str], formato: str = FORMATO
) -> str:
    """Escribe el CSV curado (`.gz` si la ruta lo pide). -> sha256 del contenido."""
    cuerpo = _cuerpo(filas, COLUMNAS_DE[formato])
    sha = _sha256(cuerpo)
    comentarios = {"formato": formato, **cabecera, "contenido_sha256": sha}
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
    if cabecera.get("formato") not in FORMATOS:
        raise FormatoInvalido(
            f"falta la cabecera `# formato: {FORMATO}` o `{FORMATO_V2}` (el archivo dice "
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
