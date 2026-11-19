"""Provincias de Argentina: slug (parámetro `PROVINCIA=`) -> código ISO 3166-2.

SEPA trae el código en `sucursales_provincia` («AR-N») y OSM lo trae en la etiqueta
`ISO3166-2` de la relación de la provincia, así que el mismo código sirve de filtro
en las dos fuentes. Para sumar otro país, se agrega su propia tabla.
"""

PROVINCIAS_AR = {
    "buenos-aires": "AR-B",
    "catamarca": "AR-K",
    "chaco": "AR-H",
    "chubut": "AR-U",
    "caba": "AR-C",
    "cordoba": "AR-X",
    "corrientes": "AR-W",
    "entre-rios": "AR-E",
    "formosa": "AR-P",
    "jujuy": "AR-Y",
    "la-pampa": "AR-L",
    "la-rioja": "AR-F",
    "mendoza": "AR-M",
    "misiones": "AR-N",
    "neuquen": "AR-Q",
    "rio-negro": "AR-R",
    "salta": "AR-A",
    "san-juan": "AR-J",
    "san-luis": "AR-D",
    "santa-cruz": "AR-Z",
    "santa-fe": "AR-S",
    "santiago-del-estero": "AR-G",
    "tierra-del-fuego": "AR-V",
    "tucuman": "AR-T",
}


def codigo_provincia(slug: str) -> str:
    """«misiones» -> «AR-N». Acepta también el código directo («AR-N»)."""
    s = slug.strip().lower()
    if s.upper() in PROVINCIAS_AR.values():
        return s.upper()
    try:
        return PROVINCIAS_AR[s.replace("_", "-").replace(" ", "-")]
    except KeyError:
        raise SystemExit(
            f"Provincia desconocida: {slug!r}. Opciones: {', '.join(sorted(PROVINCIAS_AR))}"
        ) from None
