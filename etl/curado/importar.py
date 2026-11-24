"""Importa un CSV curado (`catalogo_curado_v1`) al catálogo, con validación en seco.

    python -m etl.curado.importar ARCHIVO [--aplicar] [--forzar]

Sin `--aplicar` es un simulacro: corre exactamente la misma fusión que la importación real
(`fusionar_lote` con `fuente = 'curado'`, o sea con normalizador, calidad, prioridad entre
fuentes y campos bloqueados), pero cada lote dentro de una transacción que se revierte. Por eso
el reporte no puede divergir de lo que pasaría de verdad.

Con `--aplicar` escribe y deja una fila en `catalogo_lotes` (hash del contenido, versión del
normalizador, hash de las fuentes de entrada): el archivo se puede borrar después, porque se
puede volver a armar con `python -m etl.curado.exportar` y comprobar que el hash coincide.
Importar de nuevo el mismo archivo con la misma versión del normalizador no hace nada (se
avisa); `--forzar` lo corre igual.
"""

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import asyncpg

from etl.comun.catalogo import Reporte, conectar, fusionar_lote
from etl.comun.normalizar import NORMALIZADOR_VERSION
from etl.curado.formato import FORMATO, FilaInvalida, fila_a_producto, leer

_CAMPOS = (
    "nombre",
    "marca",
    "tamano_valor",
    "tamano_unidad",
    "pack_cantidad",
    "presentacion",
    "imagen_url",
)
_SQL_FOTO = (
    "select ean, origen, "
    + ", ".join(_CAMPOS)
    + " from productos_canonicos where ean = any ($1::text[])"
)
MAX_EJEMPLOS = 20


class _Revertir(Exception):
    """Corta el lote del simulacro para que Postgres deshaga todo."""


@dataclass
class ReporteImport:
    sha256: str
    nombre_archivo: str
    aplicado: bool
    leidas: int = 0
    validas: int = 0
    duplicados: int = 0
    nuevos: int = 0
    cambiados: int = 0
    iguales: int = 0
    cambia_origen: int = 0  # mismos datos, pero ahora figuran como `curado`
    invalidas: Counter = field(default_factory=Counter)
    ejemplos_invalidos: list[tuple[int, str, str]] = field(
        default_factory=list
    )  # línea, ean, motivo
    ejemplos_cambios: list[dict] = field(default_factory=list)
    editado: bool = False
    ya_importado: UUID | None = None
    lote_id: UUID | None = None
    fusion: Reporte = field(default_factory=Reporte)

    def texto(self) -> str:
        modo = "IMPORTADO" if self.aplicado else "SIMULACRO (no se escribió nada)"
        lineas = [
            f"{modo}: {self.nombre_archivo}  sha256 {self.sha256[:16]}…",
            f"Filas leídas:        {self.leidas}",
            f"  inválidas:         {sum(self.invalidas.values())}",
            f"  repetidas en el archivo (gana la última): {self.duplicados}",
            f"Se insertan (EAN nuevos): {self.nuevos}",
            f"Se actualizan:       {self.cambiados}",
            f"Sin cambios en los datos: {self.iguales}",
            f"  (de todos, pasan a figurar como `curado`: {self.cambia_origen})",
            f"Conflictos nuevos a revisar: {self.fusion.conflictos_nuevos}",
        ]
        for motivo, n in self.invalidas.most_common():
            lineas.append(f"    inválida por {motivo}: {n}")
        for linea, ean, motivo in self.ejemplos_invalidos:
            lineas.append(f"    línea {linea} (ean {ean or '-'}): {motivo}")
        if self.ejemplos_cambios:
            lineas.append("Ejemplos de cambios:")
            for e in self.ejemplos_cambios:
                cambios = ", ".join(f"{c}: {a!r} → {d!r}" for c, (a, d) in e["cambios"].items())
                lineas.append(f"    {e['ean']}  {cambios}")
        if self.editado:
            lineas.append(
                "AVISO: el archivo fue editado después de generarlo (el hash no coincide)."
            )
        if self.ya_importado:
            lineas.append(
                f"AVISO: este archivo ya se importó (lote {self.ya_importado}) con esta versión "
                "del normalizador. Usá --forzar para correrlo de todos modos."
            )
        if self.lote_id:
            lineas.append(f"Lote registrado: {self.lote_id}")
        return "\n".join(lineas)


def _fuentes_entrada(cabecera: dict[str, str]) -> list[dict[str, str]]:
    """`# fuentes: off.csv.gz:<sha256>, sepa.zip:<sha256>` -> [{nombre, sha256}]."""
    salida = []
    for parte in (cabecera.get("fuentes") or "").split(","):
        nombre, _, sha = parte.strip().rpartition(":")
        if nombre and len(sha) == 64:
            salida.append({"nombre": nombre, "sha256": sha})
    return salida


def _texto(valor) -> str | None:
    return None if valor is None else str(valor)


def _diferencias(antes, despues) -> dict[str, list]:
    return {c: [_texto(antes[c]), _texto(despues[c])] for c in _CAMPOS if antes[c] != despues[c]}


async def _lote(conn: asyncpg.Connection, productos, r: ReporteImport, aplicar: bool) -> None:
    """Fusiona un lote y mide qué pasó con cada EAN (antes vs después)."""
    eans = [p.ean for p in productos]
    estadisticas: dict = {}

    async def correr() -> None:
        antes = {x["ean"]: x for x in await conn.fetch(_SQL_FOTO, eans)}
        await fusionar_lote(conn, "curado", productos, r.fusion)
        despues = {x["ean"]: x for x in await conn.fetch(_SQL_FOTO, eans)}
        n = c = i = o = 0
        for ean in eans:
            if ean not in antes:
                n += 1
                continue
            o += antes[ean]["origen"] != despues[ean]["origen"]
            dif = _diferencias(antes[ean], despues[ean])
            if dif:
                c += 1
                if len(r.ejemplos_cambios) < MAX_EJEMPLOS:
                    r.ejemplos_cambios.append({"ean": ean, "cambios": dif})
            else:
                i += 1
        estadisticas.update(n=n, c=c, i=i, o=o)

    if aplicar:
        await correr()
    else:
        try:
            async with conn.transaction():
                await correr()
                raise _Revertir
        except _Revertir:
            pass
    r.nuevos += estadisticas["n"]
    r.cambiados += estadisticas["c"]
    r.iguales += estadisticas["i"]
    r.cambia_origen += estadisticas["o"]


async def importar(
    ruta: Path,
    aplicar: bool = False,
    forzar: bool = False,
    subido_por: UUID | None = None,
    etl_ejecucion_id: UUID | None = None,
    lote: int = 20_000,
    nombre_archivo: str | None = None,
) -> ReporteImport:
    lectura = leer(ruta)  # FormatoInvalido (ValueError) si no es un CSV curado
    r = ReporteImport(lectura.sha256, nombre_archivo or ruta.name, aplicar)
    declarado = lectura.cabecera.get("contenido_sha256") or None
    r.editado = declarado is not None and declarado != lectura.sha256

    productos = {}
    for linea, fila in lectura.filas:
        r.leidas += 1
        try:
            p = fila_a_producto(
                fila, {"archivo_sha256": lectura.sha256, "formato": lectura.cabecera["formato"]}
            )
        except FilaInvalida as e:
            r.invalidas[e.motivo] += 1
            if len(r.ejemplos_invalidos) < MAX_EJEMPLOS:
                r.ejemplos_invalidos.append((linea, fila.get("ean", ""), e.motivo))
            continue
        if p.ean in productos:
            r.duplicados += 1
        productos[p.ean] = p
    r.validas = len(productos)

    conn = await conectar()
    try:
        previo = await conn.fetchval(
            "select id from catalogo_lotes where sha256 = $1 and version_normalizador = $2"
            " order by creado_en desc limit 1",
            lectura.sha256,
            NORMALIZADOR_VERSION,
        )
        if previo and aplicar and not forzar:
            r.ya_importado = previo
            return r
        r.ya_importado = previo
        lista = list(productos.values())
        for i in range(0, len(lista), lote):
            await _lote(conn, lista[i : i + lote], r, aplicar)
        if aplicar:
            r.lote_id = await conn.fetchval(
                "insert into catalogo_lotes (formato, version_normalizador, nombre_archivo, sha256,"
                " sha256_declarado, filas, nuevos, cambiados, iguales, invalidos, fuentes_entrada,"
                " subido_por, etl_ejecucion_id)"
                " values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12,$13)"
                " returning id",
                FORMATO,
                NORMALIZADOR_VERSION,
                r.nombre_archivo,
                lectura.sha256,
                declarado,
                r.leidas,
                r.nuevos,
                r.cambiados,
                r.iguales,
                sum(r.invalidas.values()),
                json.dumps(_fuentes_entrada(lectura.cabecera)),
                subido_por,
                etl_ejecucion_id,
            )
    finally:
        await conn.close()
    return r


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("archivo", type=Path, help="CSV curado (.csv o .csv.gz)")
    ap.add_argument("--aplicar", action="store_true", help="escribe (sin esto es un simulacro)")
    ap.add_argument("--forzar", action="store_true", help="importar aunque ya se haya importado")
    ap.add_argument("--lote", type=int, default=20_000)
    args = ap.parse_args()
    if not args.archivo.exists():
        raise SystemExit(f"No existe {args.archivo}. Ver `make catalogo-csv-exportar`.")
    try:
        r = asyncio.run(importar(args.archivo, args.aplicar, args.forzar, lote=args.lote))
    except ValueError as e:
        raise SystemExit(f"{args.archivo}: {e}") from None
    print(r.texto())
    if not args.aplicar:
        print("\nEra un simulacro. Para escribir: agregá --aplicar (make … APLICAR=1).")


if __name__ == "__main__":
    main()
