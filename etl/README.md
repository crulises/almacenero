# ETL del catálogo

Un pipeline por fuente (NO son seeds), todos al mismo destino: `productos_canonicos`.
Los datos crudos van en `etl/data/` (ignorado por git). Mediciones, licencias y
decisiones: `docs/05-fuentes-catalogo.md`.

```
etl/comun/   conexión, EAN, tamaño y fusión al catálogo (compartido)
etl/sepa/    SEPA / Precios Claros (Argentina): fuente principal para Argentina
etl/off/     Open Food Facts (CSV): Argentina y vecinos por defecto
etl/osm/     OpenStreetMap (extracto de Geofabrik) -> locales
etl/sepa/locales.py   sucursales de SEPA -> locales
etl/conflictos.py   revisión manual de desacuerdos entre fuentes
```

Prioridad de fuentes (config `catalogo_prioridad_fuentes`): `manual > sepa > off`.
Trazabilidad: `productos_canonicos.origen` es la fuente del dato vigente y
`producto_fuentes` guarda lo que cada fuente dijo de cada EAN.

```bash
# SEPA: bajar uno o más zips diarios (URL del recurso en datos.produccion.gob.ar) y cargar
make etl-sepa-descargar SEPA_URL=https://datos.produccion.gob.ar/.../sepa_domingo.zip
make etl-sepa SEPA_ARCHIVOS="etl/data/sepa/sepa_domingo.zip"

# OFF: muestra de 30 MB, o el volcado completo (~1,4 GiB, bajarlo solo con OK)
make etl-off-muestra
make etl-off OFF_ARCHIVO=etl/data/off-muestra.csv.gz     # AR + vecinos
make etl-off OFF_PAISES=                                 # todo el mundo (2,4 GB en la base)

make conflictos

# LOCALES (destino: `locales`, con verificado=false; anti-duplicados por nombre+distancia)
make etl-osm-descargar                    # extracto de Argentina de Geofabrik (~440 MB)
make etl-osm PROVINCIA=misiones           # supermercados y almacenes de OSM con nombre+calle
make etl-sepa-locales PROVINCIA=misiones  # sucursales de SEPA (sin PROVINCIA: todo el país)
```

`PROVINCIA` es un slug (`misiones`, `buenos-aires`, `caba`...) o el código `AR-N`.
Para sumar otra provincia se repite el comando con otro valor. El extracto de OSM
necesita `pyosmium`, que viene en el extra `etl` (`make venv` lo instala).

Cargar siempre es idempotente: repetir una corrida no duplica ni pisa lo resuelto a mano.
