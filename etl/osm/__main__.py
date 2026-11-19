"""ETL de OpenStreetMap -> `locales` (supermercados y almacenes).

Lee un extracto de Geofabrik (`argentina-latest.osm.pbf`), se queda con los objetos
`shop=supermarket|convenience` de UNA provincia y carga los que tengan **nombre, calle y
coordenadas** (el número de puerta no hace falta). Entran con `verificado = false`,
`creado_por = null` y `fuente = 'osm'`; el vínculo `local_fuentes` guarda `node/<id>` o
`way/<id>`. Si ya hay un local parecido a pocos metros (por ejemplo una sucursal de
SEPA), no se crea otro: se le agrega el vínculo.

La provincia se recorta con su límite administrativo de OSM (relación con
`ISO3166-2=AR-N`, etc.), que viene en el mismo extracto; el recorte lo hace PostGIS.
Geofabrik no parte Argentina por provincia: se baja el país una vez (~440 MB).

    python -m etl.osm ARCHIVO.osm.pbf --provincia misiones

Datos: © colaboradores de OpenStreetMap, ODbL (https://www.openstreetmap.org/copyright).
"""

import argparse
import asyncio
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import osmium

from etl.comun.catalogo import conectar
from etl.comun.locales import Local, ReporteLocales, fusionar_locales
from etl.comun.provincias import codigo_provincia

FUENTE = "osm"
TIPOS_SHOP = {"supermarket", "convenience"}
# Etiquetas que se guardan crudas en `local_fuentes.datos`.
ETIQUETAS = (
    "shop",
    "name",
    "brand",
    "operator",
    "addr:street",
    "addr:housenumber",
    "addr:city",
    "addr:postcode",
    "opening_hours",
    "phone",
    "check_date",
)


@dataclass
class Comercio:
    """Un `shop` de OSM tal como se lee del archivo, antes de filtrar."""

    tipo: str  # node | way
    osm_id: int
    lat: float | None
    lng: float | None
    etiquetas: dict[str, str]
    editado: str | None


@dataclass
class Lectura:
    comercios: list[Comercio] = field(default_factory=list)
    limite_wkt: str | None = None  # límite de la provincia pedida (MultiPolygon WKT)


def _etiquetas(obj) -> dict[str, str]:
    return {k: obj.tags[k] for k in ETIQUETAS if k in obj.tags}


def _centro(way) -> tuple[float, float] | None:
    """Centro de la caja de un camino cerrado (un local mapeado como edificio)."""
    lats, lngs = [], []
    for n in way.nodes:
        if n.location.valid():
            lats.append(n.location.lat)
            lngs.append(n.location.lon)
    if not lats:
        return None
    return (min(lats) + max(lats)) / 2, (min(lngs) + max(lngs)) / 2


def leer_pbf(ruta: Path, iso: str) -> Lectura:
    """Una pasada por el archivo: comercios del país + límite de la provincia `iso`."""
    lectura = Lectura()
    fp = (
        osmium.FileProcessor(str(ruta))
        .with_locations()
        # Solo se arman áreas para relaciones de límites administrativos.
        .with_areas(osmium.filter.TagFilter(("boundary", "administrative")))
        # A mi código solo llegan objetos con `shop` o `boundary`.
        .with_filter(osmium.filter.KeyFilter("shop", "boundary"))
    )
    fabrica = osmium.geom.WKTFactory()
    for obj in fp:
        if isinstance(obj, osmium.osm.Area):
            if (
                not obj.from_way()
                and obj.tags.get("boundary") == "administrative"
                and obj.tags.get("ISO3166-2") == iso
            ):
                lectura.limite_wkt = fabrica.create_multipolygon(obj)
            continue
        if obj.tags.get("shop") not in TIPOS_SHOP:
            continue
        editado = obj.timestamp.strftime("%Y-%m-%d") if obj.timestamp else None
        if isinstance(obj, osmium.osm.Node):
            lat, lng = obj.location.lat, obj.location.lon
            tipo = "node"
        elif isinstance(obj, osmium.osm.Way):
            centro = _centro(obj)
            lat, lng = centro if centro else (None, None)
            tipo = "way"
        else:
            continue
        lectura.comercios.append(Comercio(tipo, obj.id, lat, lng, _etiquetas(obj), editado))
    return lectura


async def en_provincia(conn, comercios: list[Comercio], limite_wkt: str) -> list[Comercio]:
    """Los comercios con coordenadas que caen dentro del límite (lo decide PostGIS)."""
    con_coord = [c for c in comercios if c.lat is not None and c.lng is not None]
    adentro = await conn.fetch(
        """
        select i - 1 as idx
        from unnest($1::float8[], $2::float8[]) with ordinality as t(lat, lng, i),
             (select st_geomfromtext($3, 4326) as g) b
        where st_covers(b.g, st_setsrid(st_makepoint(t.lng, t.lat), 4326))
        """,
        [c.lat for c in con_coord],
        [c.lng for c in con_coord],
        limite_wkt,
    )
    return [con_coord[r["idx"]] for r in adentro]


def transformar(c: Comercio, reporte: ReporteLocales) -> Local | None:
    """Un comercio de OSM -> `Local`, o None si le falta nombre o calle."""
    reporte.leidos += 1
    nombre = " ".join(c.etiquetas.get("name", "").split())
    if len(nombre) < 2:
        reporte.descartados["sin_nombre"] += 1
        return None
    calle = " ".join(c.etiquetas.get("addr:street", "").split())
    if len(calle) < 2:
        reporte.descartados["sin_calle"] += 1
        return None
    numero = c.etiquetas.get("addr:housenumber", "").strip()
    ciudad = " ".join(c.etiquetas.get("addr:city", "").split())
    direccion = calle + (f" {numero}" if numero else "") + (f", {ciudad}" if ciudad else "")
    return Local(
        fuente=FUENTE,
        ref=f"{c.tipo}/{c.osm_id}",
        nombre=nombre,
        direccion=direccion,
        lat=c.lat,  # type: ignore[arg-type]  # ya filtrado: tiene coordenadas
        lng=c.lng,  # type: ignore[arg-type]
        datos={**c.etiquetas, "editado": c.editado},
    )


def a_locales(comercios: Iterable[Comercio], reporte: ReporteLocales) -> list[Local]:
    return [loc for c in comercios if (loc := transformar(c, reporte)) is not None]


async def cargar(ruta: Path, provincia: str) -> ReporteLocales:
    iso = codigo_provincia(provincia)
    print(f"Leyendo {ruta.name} ({iso})...", file=sys.stderr, flush=True)
    lectura = await asyncio.to_thread(leer_pbf, ruta, iso)
    if lectura.limite_wkt is None:
        raise SystemExit(f"El archivo no trae el límite de la provincia {iso} (ISO3166-2).")
    reporte = ReporteLocales()
    conn = await conectar()
    try:
        adentro = await en_provincia(conn, lectura.comercios, lectura.limite_wkt)
        print(
            f"  comercios shop=supermarket|convenience: {len(lectura.comercios)} en el país, "
            f"{len(adentro)} en {iso}",
            file=sys.stderr,
            flush=True,
        )
        await fusionar_locales(conn, a_locales(adentro, reporte), reporte)
    finally:
        await conn.close()
    return reporte


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("archivo", type=Path, help="extracto .osm.pbf de Geofabrik")
    ap.add_argument("--provincia", required=True, help="slug o código: misiones, AR-N, ...")
    args = ap.parse_args()
    if not args.archivo.exists():
        raise SystemExit(f"No existe {args.archivo}. Ver `make etl-osm-descargar`.")
    print(asyncio.run(cargar(args.archivo, args.provincia)).texto())


if __name__ == "__main__":
    main()
