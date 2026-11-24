"""Exporta el catálogo **de la base** al formato de intercambio `catalogo_curado_v2` (docs/09).

    python -m etl.curado.exportar_base NOMBRE.csv[.gz]

A diferencia de `etl.curado.exportar` (que arma el CSV desde las fuentes crudas), esto vuelca
lo que el catálogo ya es: datos del producto + los **metadatos del tratamiento** (de dónde
viene, qué campos tiene bloqueados por una persona, si lo cargó/corrigió alguien, sugerencias,
avisos del normalizador, conflictos). El archivo se puede importar en este u otro proyecto
(`etl.curado.importar`) y deja el catálogo como estaba, sin repetir el trabajo manual.

Los metadatos son **conteos y banderas**: no llevan ids de usuarios ni de la base.
"""

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from etl.comun.catalogo import conectar
from etl.comun.normalizar import NORMALIZADOR_VERSION
from etl.comun.rutas import NombreInvalido, ruta_de_salida
from etl.curado.exportar import ResultadoExport
from etl.curado.formato import FORMATO_V2, SEP_LISTA, escribir

_SQL = """
select p.ean, p.nombre, p.marca, p.tamano_valor, p.tamano_unidad, p.pack_cantidad,
       p.presentacion, p.imagen_url, p.origen, p.campos_bloqueados, p.calidad,
       p.estado_calidad, p.calidad_motivos, p.normalizador_version,
       coalesce(a.ediciones, 0) as ediciones_admin,
       coalesce(s.aprobadas, 0) as sugerencias_aprobadas,
       coalesce(s.rechazadas, 0) as sugerencias_rechazadas,
       coalesce(s.pendientes, 0) as sugerencias_pendientes,
       coalesce(av.n, 0) as avisos_normalizador,
       coalesce(c.resueltos, 0) as conflictos_resueltos,
       coalesce(c.pendientes, 0) as conflictos_pendientes
  from productos_canonicos p
  left join (select entidad_id, count(*) as ediciones from auditoria_admin
              where entidad = 'producto'
                and accion in ('producto.crear', 'producto.corregir')
              group by entidad_id) a on a.entidad_id = p.id::text
  left join (select ean,
                    count(*) filter (where estado = 'aprobada') as aprobadas,
                    count(*) filter (where estado = 'rechazada') as rechazadas,
                    count(*) filter (where estado = 'pendiente') as pendientes
               from sugerencias_catalogo group by ean) s on s.ean = p.ean
  left join (select ean, count(*) as n from avisos_catalogo group by ean) av on av.ean = p.ean
  left join (select ean,
                    count(*) filter (where estado = 'resuelto') as resueltos,
                    count(*) filter (where estado = 'pendiente') as pendientes
               from conflictos_catalogo group by ean) c on c.ean = p.ean
 where ($1::text is null or p.ean like $1 || '%')
 order by p.ean
"""


def fila_de_producto(r) -> dict[str, str]:
    """Una fila del catálogo -> fila v2 (todas las celdas como texto)."""
    cargado = r["origen"] == "manual" or r["ediciones_admin"] > 0 or r["sugerencias_aprobadas"] > 0
    revisado = (
        cargado
        or bool(r["campos_bloqueados"])
        or r["sugerencias_rechazadas"] > 0
        or r["conflictos_resueltos"] > 0
    )
    return {
        "ean": r["ean"],
        "nombre": r["nombre"],
        "marca": r["marca"] or "",
        "tamano_valor": format(r["tamano_valor"].normalize(), "f") if r["tamano_valor"] else "",
        "tamano_unidad": r["tamano_unidad"] or "",
        "pack_cantidad": str(r["pack_cantidad"]) if r["pack_cantidad"] else "",
        "presentacion": r["presentacion"] or "",
        "imagen_url": r["imagen_url"] or "",
        "fuente_origen": r["origen"],
        "nota": "",
        "origen": r["origen"],
        "campos_bloqueados": SEP_LISTA.join(sorted(r["campos_bloqueados"])),
        "calidad": "" if r["calidad"] is None else str(r["calidad"]),
        "estado_calidad": r["estado_calidad"] or "",
        "calidad_motivos": SEP_LISTA.join(r["calidad_motivos"] or ()),
        "normalizador_version": (
            "" if r["normalizador_version"] is None else str(r["normalizador_version"])
        ),
        "cargado_a_mano": "1" if cargado else "0",
        "revisado": "1" if revisado else "0",
        "ediciones_admin": str(r["ediciones_admin"]),
        "sugerencias_aprobadas": str(r["sugerencias_aprobadas"]),
        "sugerencias_rechazadas": str(r["sugerencias_rechazadas"]),
        "sugerencias_pendientes": str(r["sugerencias_pendientes"]),
        "avisos_normalizador": str(r["avisos_normalizador"]),
        "conflictos_resueltos": str(r["conflictos_resueltos"]),
        "conflictos_pendientes": str(r["conflictos_pendientes"]),
    }


async def exportar_base(salida: Path, prefijo_ean: str | None = None) -> ResultadoExport:
    """`prefijo_ean`: solo para tests (exportar un subconjunto)."""
    conn = await conectar()
    try:
        filas: list[dict[str, str]] = []
        por_origen: Counter = Counter()
        async with conn.transaction():  # el cursor necesita transacción
            async for r in conn.cursor(_SQL, prefijo_ean, prefetch=5000):
                filas.append(fila_de_producto(r))
                por_origen[r["origen"]] += 1
    finally:
        await conn.close()
    cabecera = {
        "generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "normalizador": str(NORMALIZADOR_VERSION),
        "fuentes": "(base de datos)",
        "exportado_de": "catalogo",
    }
    sha = escribir(salida, filas, cabecera, formato=FORMATO_V2)
    return ResultadoExport(sha, {**cabecera, "contenido_sha256": sha}, len(filas), por_origen)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("salida", help="nombre del CSV (.csv o .csv.gz); va a ETL_EXPORT_DIR")
    args = ap.parse_args()
    try:
        destino = ruta_de_salida(args.salida)
    except NombreInvalido as e:
        raise SystemExit(f"SALIDA: {e}") from None
    r = asyncio.run(exportar_base(destino))
    print(f"Escrito {destino}\n{r.texto()}")


if __name__ == "__main__":
    main()
