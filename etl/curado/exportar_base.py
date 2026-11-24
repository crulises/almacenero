"""Exporta el catálogo **de la base** al formato de intercambio `catalogo_curado_v2` (docs/09).

    python -m etl.curado.exportar_base NOMBRE

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

from etl.comun.catalogo import Producto, conectar, normalizar_con_traza
from etl.comun.normalizar import NORMALIZADOR_VERSION
from etl.comun.paquete import leeme_de
from etl.comun.resumen import Trazas
from etl.comun.rutas import NombreInvalido, ruta_de_salida
from etl.curado import leeme
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


class Resumen:
    """Lo que cuenta el LEEME del catálogo: cuántos productos tienen cada tratamiento."""

    def __init__(self) -> None:
        self.por_origen: Counter = Counter()
        self.por_estado: Counter = Counter()
        self.motivos: Counter = Counter()
        self.metas: Counter = Counter()
        self.bloqueados: Counter = Counter()
        self.trazas = Trazas()  # qué reglas aplicaría hoy el normalizador sobre lo exportado

    def agregar(self, r, fila: dict[str, str]) -> None:
        self.por_origen[r["origen"]] += 1
        self.por_estado[r["estado_calidad"] or "sin calcular"] += 1
        self.motivos.update(r["calidad_motivos"] or ())
        for k in ("cargado_a_mano", "revisado"):
            self.metas[k] += fila[k] == "1"
        for k in (
            "ediciones_admin",
            "sugerencias_aprobadas",
            "sugerencias_rechazadas",
            "sugerencias_pendientes",
            "avisos_normalizador",
            "conflictos_resueltos",
            "conflictos_pendientes",
        ):
            self.metas[k] += r[k] > 0  # productos con al menos uno
        self.bloqueados.update(r["campos_bloqueados"])
        p = Producto(
            r["ean"],
            r["nombre"],
            r["marca"],
            r["tamano_valor"],
            r["tamano_unidad"],
            r["imagen_url"],
        )
        nuevo, _, salida = normalizar_con_traza(p)
        self.trazas.agregar(salida, r["nombre"], nuevo.nombre)


_ROTULOS = {
    "cargado_a_mano": "cargados o corregidos a mano por una persona",
    "revisado": "revisados por una persona (incluye lo anterior y lo bloqueado)",
    "ediciones_admin": "con ediciones del admin",
    "sugerencias_aprobadas": "con sugerencias de usuarios aprobadas",
    "sugerencias_rechazadas": "con sugerencias de usuarios rechazadas",
    "sugerencias_pendientes": "con sugerencias todavía pendientes",
    "avisos_normalizador": "con avisos del normalizador (cosas que no supo resolver)",
    "conflictos_resueltos": "con conflictos entre fuentes ya resueltos",
    "conflictos_pendientes": "con conflictos entre fuentes sin resolver",
}


def _seccion_tratamiento(resumen: Resumen, total: int) -> str:
    lineas = ["Cuántos productos tienen cada tratamiento (de " + str(total) + "):"]
    lineas += [f"  {_ROTULOS[k]}: {resumen.metas[k]}" for k in _ROTULOS]
    if resumen.bloqueados:
        lineas.append("Campos bloqueados por una persona (el ETL no los pisa):")
        lineas += [f"  {c}: {n}" for c, n in resumen.bloqueados.most_common()]
    else:
        lineas.append("Campos bloqueados por una persona: ninguno.")
    lineas += ["", "Estado de calidad:"]
    lineas += [f"  {e}: {n}" for e, n in resumen.por_estado.most_common()]
    return "\n".join(lineas)


async def exportar_base(salida: Path, prefijo_ean: str | None = None) -> ResultadoExport:
    """`prefijo_ean`: solo para tests (exportar un subconjunto)."""
    conn = await conectar()
    resumen = Resumen()
    try:
        filas: list[dict[str, str]] = []
        async with conn.transaction():  # el cursor necesita transacción
            async for r in conn.cursor(_SQL, prefijo_ean, prefetch=5000):
                fila = fila_de_producto(r)
                filas.append(fila)
                resumen.agregar(r, fila)
    finally:
        await conn.close()
    por_origen = resumen.por_origen
    cabecera = {
        "generado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "normalizador": str(NORMALIZADOR_VERSION),
        "fuentes": "(base de datos)",
        "exportado_de": "catalogo",
    }
    secciones = [
        ("Qué es", leeme.seccion_que_es(FORMATO_V2, len(filas), por_origen, cabecera)),
        ("Qué se hizo con los productos", _seccion_tratamiento(resumen, len(filas))),
        (
            "Reglas del normalizador",
            leeme.seccion_reglas(
                resumen.trazas,
                len(filas),
                "los productos exportados tal como están en el catálogo. Los datos ya pasaron "
                "por el normalizador al cargarse: si abajo dice «ninguna», no queda nada por "
                "cambiar con estas reglas; si lista alguna, es lo que cambiaría una "
                "renormalización",
            ),
        ),
        ("Calidad", leeme.seccion_motivos(resumen.motivos, len(filas))),
        ("Columnas", leeme.seccion_columnas(FORMATO_V2)),
        ("Cómo importarlo", leeme.seccion_importar()),
    ]
    sha = escribir(
        salida,
        filas,
        cabecera,
        formato=FORMATO_V2,
        leeme=leeme_de("Catálogo — export de intercambio con metadatos", secciones),
    )
    return ResultadoExport(
        sha,
        {**cabecera, "contenido_sha256": sha},
        len(filas),
        por_origen,
        reglas=resumen.trazas.texto(len(filas)),
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("salida", help="nombre del export (sin extensión); va a ETL_EXPORT_DIR")
    args = ap.parse_args()
    try:
        destino = ruta_de_salida(args.salida)
    except NombreInvalido as e:
        raise SystemExit(f"SALIDA: {e}") from None
    r = asyncio.run(exportar_base(destino))
    print(f"Escrito {destino}\n{r.texto()}")


if __name__ == "__main__":
    main()
