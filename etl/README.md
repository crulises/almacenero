# ETL del catálogo

Un pipeline por fuente (NO son seeds), todos al mismo destino: `productos_canonicos`.
Los datos crudos van en `etl/data/` (ignorado por git). Detalle, mediciones y
decisiones: `docs/05-fuentes-catalogo.md`.

```
etl/comun/   conexión, EAN, tamaño y fusión al catálogo (compartido)
etl/off/     Open Food Facts (CSV, todo el mundo)
etl/conflictos.py   revisión manual de desacuerdos entre fuentes
```

```bash
make etl-off-muestra     # ~30 MB para probar
make etl-off OFF_ARCHIVO=etl/data/off-muestra.csv.gz
make conflictos
```

El volcado completo (`make etl-off-descargar`, ~1,4 GiB) se baja solo con OK explícito.
