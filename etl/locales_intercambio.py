"""Intercambio de **locales** entre instalaciones: formato `locales_intercambio_v1` (docs/09 §8).

    python -m etl.locales_intercambio exportar NOMBRE [--todos]
    python -m etl.locales_intercambio importar ARCHIVO [--aplicar]

Exportar vuelca los locales **verificados** (`--todos`: también los sin verificar) a un `.zip` con
el CSV y un `LEEME.txt`. Importar los suma a la base de destino sin el «modo migración»: un
simulacro por defecto y, con `--aplicar`, lo escribe. Las reglas, por cada fila del archivo:

1. Si alguno de sus vínculos con las fuentes del ETL (`osm:node/1`, `sepa:...`) ya existe acá,
   es ese local. Si no, se busca un duplicado con la misma lógica que el alta de locales
   (nombre parecido a pocos metros). Si lo hay, es ese.
2. Si es un local que ya existe: **no se pisan sus datos** (puede haberlos corregido el admin
   de acá). Solo se le agregan los vínculos que le falten y, si el archivo lo trae verificado y
   acá no lo estaba, se lo marca verificado (esa validación es justo lo que viaja).
3. Si no existe, se crea con los datos del archivo, el mismo `fuente` y `verificado` que traía,
   sin dueño (`creado_por` null: las personas de otra instalación no existen acá) y con sus
   vínculos. `fuente` y vínculos se conservan para no mezclar datos de OSM (ODbL) con el resto.

Idempotente: importar dos veces el mismo archivo no cambia nada la segunda.
"""

import argparse
import asyncio
import csv
import hashlib
import io
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

from etl.comun.catalogo import conectar
from etl.comun.locales import (
    _SQL_DUPLICADO,
    MAX_DIRECCION,
    MAX_NOMBRE,
    METROS_DEFECTO,
    SIMILITUD_DEFECTO,
    _umbral,
)
from etl.comun.paquete import PaqueteInvalido, contenido_csv, escribir_zip, leeme_de
from etl.comun.rutas import NombreInvalido, ruta_de_salida

FORMATO = "locales_intercambio_v1"
COLUMNAS = (
    "id_origen",
    "nombre",
    "direccion",
    "lat",
    "lng",
    "fuente",
    "verificado",
    "referencias",
    "medios_pago",
    "recargo_tarjeta",
)
FUENTES_LOCAL = ("manual", "osm", "sepa")
FUENTES_VINCULO = ("osm", "sepa")
SEP = "|"
MAX_EJEMPLOS = 20


class FormatoInvalido(ValueError):
    pass


class FilaInvalida(Exception):
    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


_SQL_EXPORT = """
select l.id, l.nombre, l.direccion, st_y(l.ubicacion::geometry) as lat,
       st_x(l.ubicacion::geometry) as lng, l.fuente, l.verificado,
       l.medios_pago::text as medios_pago, l.recargo_tarjeta::text as recargo_tarjeta,
       coalesce((select array_agg(f.fuente || ':' || f.ref order by f.fuente, f.ref)
                   from local_fuentes f where f.local_id = l.id), '{}') as referencias
  from locales l
 where ($1::boolean is false or l.verificado)
   and ($2::text is null or l.nombre like $2 || '%')
 order by st_y(l.ubicacion::geometry), st_x(l.ubicacion::geometry), l.nombre, l.id
"""


def _coord(v: float) -> str:
    return f"{v:.7f}"


def fila_de_local(r) -> dict[str, str]:
    return {
        "id_origen": str(r["id"]),
        "nombre": r["nombre"],
        "direccion": r["direccion"] or "",
        "lat": _coord(r["lat"]),
        "lng": _coord(r["lng"]),
        "fuente": r["fuente"],
        "verificado": "1" if r["verificado"] else "0",
        "referencias": SEP.join(r["referencias"]),
        "medios_pago": json.dumps(json.loads(r["medios_pago"]), sort_keys=True),
        "recargo_tarjeta": json.dumps(json.loads(r["recargo_tarjeta"]), sort_keys=True),
    }


def _cuerpo(filas: list[dict[str, str]]) -> str:
    salida = io.StringIO()
    w = csv.DictWriter(salida, fieldnames=COLUMNAS, lineterminator="\n")
    w.writeheader()
    for f in sorted(filas, key=lambda f: (f["lat"], f["lng"], f["nombre"], f["id_origen"])):
        w.writerow(f)
    return salida.getvalue()


def _sha(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


@dataclass
class ResultadoExport:
    sha256: str
    filas: int
    por_fuente: Counter
    verificados: int

    def texto(self) -> str:
        lineas = [
            f"Locales escritos: {self.filas} ({self.verificados} verificados)",
            f"sha256 del contenido: {self.sha256}",
        ]
        lineas += [f"  de {f}: {n}" for f, n in self.por_fuente.most_common()]
        return "\n".join(lineas)


async def exportar(
    salida: Path, solo_verificados: bool = True, prefijo_nombre: str | None = None
) -> ResultadoExport:
    """`prefijo_nombre`: solo para tests (exportar un subconjunto)."""
    conn = await conectar()
    try:
        filas = [
            fila_de_local(r)
            for r in await conn.fetch(_SQL_EXPORT, solo_verificados, prefijo_nombre)
        ]
    finally:
        await conn.close()
    por_fuente = Counter(f["fuente"] for f in filas)
    verificados = sum(f["verificado"] == "1" for f in filas)
    cuerpo = _cuerpo(filas)
    sha = _sha(cuerpo)
    generado = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cabecera = {
        "formato": FORMATO,
        "generado": generado,
        "solo_verificados": "si" if solo_verificados else "no",
        "contenido_sha256": sha,
    }
    datos = ("".join(f"# {k}: {v}\n" for k, v in cabecera.items()) + cuerpo).encode("utf-8")
    contenido = "solo los verificados por un admin" if solo_verificados else "todos"
    secciones = [
        (
            "Qué es",
            f"Locales (comercios) en formato {FORMATO}, para llevarlos a otra instalación.\n"
            f"Generado: {generado}\n"
            f"Contenido: {contenido}.\n"
            f"Locales: {len(filas)} ({verificados} verificados)\n"
            + "\n".join(f"  de {f}: {n}" for f, n in por_fuente.most_common()),
        ),
        (
            "Qué lleva cada local",
            "id_origen (informativo), nombre, direccion, lat, lng, fuente (manual|osm|sepa),\n"
            "verificado (1|0), referencias (vínculos con OSM/SEPA, separados por |, p. ej.\n"
            "osm:node/123), medios_pago y recargo_tarjeta (JSON). No lleva personas ni el dato\n"
            "crudo de las fuentes. Los de fuente osm vienen de OpenStreetMap (licencia ODbL).",
        ),
        (
            "Cómo importarlo",
            "Panel de admin: ETL → «Importar locales», elegí este .zip (sin descomprimir) y corré\n"
            "primero el simulacro; si el reporte está bien, repetí con «aplicar».\n"
            "Por consola: make locales-importar ARCHIVO=<este .zip> [APLICAR=1]\n"
            "Un local que ya existe en el destino (mismo vínculo OSM/SEPA, o mismo nombre a pocos\n"
            "metros) no se pisa: solo se le suman los vínculos que falten y, si venía verificado,\n"
            "se lo verifica. Los demás se crean con el mismo fuente y verificado.",
        ),
    ]
    escribir_zip(
        salida, f"{salida.stem}.csv", datos, leeme_de("Locales — intercambio", secciones)(sha)
    )
    return ResultadoExport(sha, len(filas), por_fuente, verificados)


# ------------------------------------------------------------------ importar
@dataclass
class Fila:
    id_origen: str
    nombre: str
    direccion: str | None
    lat: float
    lng: float
    fuente: str
    verificado: bool
    referencias: tuple[tuple[str, str], ...]
    medios_pago: dict
    recargo_tarjeta: dict


def _objeto_json(texto: str, vacio: dict) -> dict:
    if not texto.strip():
        return vacio
    try:
        v = json.loads(texto)
    except ValueError:
        raise FilaInvalida("json_invalido") from None
    if not isinstance(v, dict):
        raise FilaInvalida("json_invalido")
    return v


def fila_a_local(f: dict[str, str]) -> Fila:
    nombre = (f.get("nombre") or "").strip()
    if len(nombre) < 2:
        raise FilaInvalida("nombre_corto")
    try:
        lat, lng = float(f.get("lat") or ""), float(f.get("lng") or "")
    except ValueError:
        raise FilaInvalida("coordenadas_invalidas") from None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise FilaInvalida("coordenadas_fuera_de_rango")
    fuente = (f.get("fuente") or "").strip() or "manual"
    if fuente not in FUENTES_LOCAL:
        raise FilaInvalida("fuente_invalida")
    verificado = (f.get("verificado") or "0").strip()
    if verificado not in ("0", "1"):
        raise FilaInvalida("verificado_invalido")
    direccion = (f.get("direccion") or "").strip()[:MAX_DIRECCION] or None
    refs = []
    for r in (f.get("referencias") or "").split(SEP):
        r = r.strip()
        if not r:
            continue
        fuente_ref, _, ref = r.partition(":")
        if fuente_ref not in FUENTES_VINCULO or not 1 <= len(ref) <= 100:
            raise FilaInvalida("referencia_invalida")
        refs.append((fuente_ref, ref))
    return Fila(
        (f.get("id_origen") or "").strip(),
        nombre[:MAX_NOMBRE],
        direccion,
        lat,
        lng,
        fuente,
        verificado == "1",
        tuple(refs),
        _objeto_json(f.get("medios_pago") or "", {}),
        _objeto_json(f.get("recargo_tarjeta") or "", {"aplica": False, "porcentaje": 0}),
    )


def leer(ruta: Path) -> tuple[dict[str, str], list[tuple[int, dict[str, str]]], str]:
    """-> (cabecera, [(línea, fila)], sha256 del contenido). Lanza `FormatoInvalido`."""
    try:
        crudo = contenido_csv(ruta.read_bytes())
    except PaqueteInvalido as e:
        raise FormatoInvalido(str(e)) from None
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
            f"{cabecera.get('formato')!r}): no es un export de locales de este proyecto"
        )
    cuerpo = "\n".join(lineas[i:])
    lector = csv.DictReader(io.StringIO(cuerpo, newline=""))
    if not lector.fieldnames or not {"nombre", "lat", "lng"} <= set(lector.fieldnames):
        raise FormatoInvalido("faltan las columnas `nombre`, `lat` y `lng`")
    filas = []
    anterior = lector.line_num
    for f in lector:
        filas.append((i + anterior + 1, {c: (v or "") for c, v in f.items() if c is not None}))
        anterior = lector.line_num
    return cabecera, filas, _sha(cuerpo)


@dataclass
class ReporteImport:
    sha256: str
    nombre_archivo: str
    aplicado: bool
    leidas: int = 0
    invalidas: Counter = field(default_factory=Counter)
    ejemplos_invalidos: list[tuple[int, str, str]] = field(default_factory=list)
    nuevos: int = 0
    existentes: int = 0  # ya estaban (por vínculo o por nombre + distancia)
    verificados_ahora: int = 0  # existentes que acá no estaban verificados y ahora sí
    vinculos_nuevos: int = 0
    editado: bool = False
    ejemplos_nuevos: list[str] = field(default_factory=list)

    def texto(self) -> str:
        modo = "IMPORTADO" if self.aplicado else "SIMULACRO (no se escribió nada)"
        lineas = [
            f"{modo}: {self.nombre_archivo}  sha256 {self.sha256[:16]}…",
            f"Locales leídos:            {self.leidas}",
            f"  inválidos:               {sum(self.invalidas.values())}",
            f"Se crean (no existían):    {self.nuevos}",
            f"Ya existían (no se pisan): {self.existentes}",
            f"  de esos, pasan a verificados: {self.verificados_ahora}",
            f"Vínculos nuevos con OSM/SEPA: {self.vinculos_nuevos}",
        ]
        for motivo, n in self.invalidas.most_common():
            lineas.append(f"    inválido por {motivo}: {n}")
        for linea, id_, motivo in self.ejemplos_invalidos:
            lineas.append(f"    línea {linea} (id {id_ or '-'}): {motivo}")
        if self.ejemplos_nuevos:
            lineas.append("Ejemplos de locales que se crean:")
            lineas += [f"    {e}" for e in self.ejemplos_nuevos]
        if self.editado:
            lineas.append(
                "AVISO: el archivo fue editado después de generarlo (el hash no coincide)."
            )
        return "\n".join(lineas)


class _Revertir(Exception):
    pass


_SQL_POR_VINCULO = "select local_id from local_fuentes where fuente = $1 and ref = $2"
_SQL_NUEVO = """
insert into locales (nombre, direccion, ubicacion, medios_pago, recargo_tarjeta, fuente,
                     verificado, creado_por)
values ($1, $2, st_setsrid(st_makepoint($4, $3), 4326)::geography, $5::jsonb, $6::jsonb, $7, $8,
        null)
returning id
"""


async def _fusionar(
    conn: asyncpg.Connection, filas: list[Fila], r: ReporteImport, metros: float, similitud: float
) -> None:
    for f in filas:
        local_id = None
        for fuente, ref in f.referencias:
            local_id = await conn.fetchval(_SQL_POR_VINCULO, fuente, ref)
            if local_id:
                break
        if local_id is None:
            local_id = await conn.fetchval(
                _SQL_DUPLICADO, f.lat, f.lng, metros, f.nombre, similitud
            )
        if local_id is None:
            local_id = await conn.fetchval(
                _SQL_NUEVO,
                f.nombre,
                f.direccion,
                f.lat,
                f.lng,
                json.dumps(f.medios_pago),
                json.dumps(f.recargo_tarjeta),
                f.fuente,
                f.verificado,
            )
            r.nuevos += 1
            if len(r.ejemplos_nuevos) < 5:
                r.ejemplos_nuevos.append(f"{f.nombre} ({f.lat:.4f}, {f.lng:.4f}) [{f.fuente}]")
        else:
            r.existentes += 1
            if f.verificado:
                n = await conn.fetchval(
                    "update locales set verificado = true where id = $1 and not verificado"
                    " returning 1",
                    local_id,
                )
                r.verificados_ahora += n or 0
        for fuente, ref in f.referencias:
            insertado = await conn.fetchval(
                "insert into local_fuentes (local_id, fuente, ref) values ($1, $2, $3)"
                " on conflict (fuente, ref) do nothing returning 1",
                local_id,
                fuente,
                ref,
            )
            r.vinculos_nuevos += insertado or 0


async def importar(
    ruta: Path, aplicar: bool = False, nombre_archivo: str | None = None
) -> ReporteImport:
    cabecera, crudas, sha = leer(ruta)
    r = ReporteImport(sha, nombre_archivo or ruta.name, aplicar)
    declarado = cabecera.get("contenido_sha256")
    r.editado = bool(declarado) and declarado != sha
    validas: list[Fila] = []
    for linea, fila in crudas:
        r.leidas += 1
        try:
            validas.append(fila_a_local(fila))
        except FilaInvalida as e:
            r.invalidas[e.motivo] += 1
            if len(r.ejemplos_invalidos) < MAX_EJEMPLOS:
                r.ejemplos_invalidos.append((linea, fila.get("id_origen", ""), e.motivo))
    conn = await conectar()
    try:
        metros = await _umbral(conn, "local_duplicado_metros", METROS_DEFECTO)
        similitud = await _umbral(conn, "local_duplicado_similitud", SIMILITUD_DEFECTO)
        try:
            async with conn.transaction():
                await _fusionar(conn, validas, r, metros, similitud)
                if not aplicar:
                    raise _Revertir
        except _Revertir:
            pass
    finally:
        await conn.close()
    return r


def _publicar(destino) -> str:
    """Además del disco del worker, deja el export en el almacén (S3) si hay uno configurado."""
    from etl.comun.almacen import AlmacenError, publicar_archivo

    try:
        return publicar_archivo(destino)
    except AlmacenError as e:
        return f"AVISO: no se pudo subir al almacén ({e}). El archivo local está intacto."


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("exportar", help="vuelca los locales verificados a un .zip")
    e.add_argument("salida", help="nombre del export (sin extensión); va a ETL_EXPORT_DIR")
    e.add_argument("--todos", action="store_true", help="también los sin verificar")
    i = sub.add_parser("importar", help="valida (simulacro) o importa un export de locales")
    i.add_argument("archivo", type=Path)
    i.add_argument("--aplicar", action="store_true", help="escribe (sin esto es un simulacro)")
    args = ap.parse_args()
    if args.cmd == "exportar":
        try:
            destino = ruta_de_salida(args.salida)
        except NombreInvalido as ex:
            raise SystemExit(f"SALIDA: {ex}") from None
        res = asyncio.run(exportar(destino, not args.todos))
        print(f"Escrito {destino}\n{res.texto()}")
        print(_publicar(destino))
        return
    if not args.archivo.exists():
        raise SystemExit(f"No existe {args.archivo}. Ver `make locales-exportar`.")
    try:
        rep = asyncio.run(importar(args.archivo, args.aplicar))
    except ValueError as ex:
        raise SystemExit(f"{args.archivo}: {ex}") from None
    print(rep.texto())
    if not args.aplicar:
        print("\nEra un simulacro. Para escribir: agregá --aplicar (make … APLICAR=1).")


if __name__ == "__main__":
    main()
