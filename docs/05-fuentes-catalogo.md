# Doc 5 — Fuentes de catálogo y de locales (corte 7)

Investigación y decisiones del corte 7 de v0.0.2. Las mediciones son del
2026-11-16; cuando algo **no** se pudo verificar, se dice. No es fuente de verdad
del producto (Doc 1) ni de la arquitectura (Doc 2).

## 1. Qué quedó implementado

- **Un ETL por fuente, un solo destino.** `etl/off/` (Open Food Facts) escribe a
  `productos_canonicos` a través de una capa mínima compartida (`etl/comun/`:
  conexión, validación de EAN, normalización de tamaño, fusión por lotes en SQL).
- **Tablas** (migración `20261116000001_catalogo_fuentes.sql`):
  - `producto_fuentes (ean, fuente, datos jsonb, cargado_en)`: el dato crudo de cada
    fuente. Su PK `(ean, fuente)` es también el índice por EAN.
  - `conflictos_catalogo`: A = lo que hay en el catálogo, B = lo que trae la otra
    fuente; `pendiente` / `resuelto`, quién y cuándo. El mismo desacuerdo no se reabre.
  - `productos_canonicos.campos_bloqueados`: lo que el admin resolvió. Un trigger
    impide cambiar un campo bloqueado salvo dentro de la resolución de un conflicto
    (misma técnica que el karma y el rol).
  - Funciones de integridad/comparación: `prioridad_fuente`, `textos_similares`
    (pg_trgm + unaccent), `tamanos_equivalentes`.
- **Qué es un conflicto:** tamaño distinto tras llevar a g/ml/u (tolerancia 1 %), o
  nombre/marca muy distintos por similitud. Mayúsculas, acentos y «Aceite Girasol» vs.
  «aceite de girasol» no cuentan.
- **Prioridad de fuentes:** config `catalogo_prioridad_fuentes` (array JSON, mayor a
  menor); sin config rige `manual > off > sepa`. Una fuente de menor prioridad solo
  completa campos vacíos y deja los desacuerdos como conflicto; nunca pisa lo manual.
- **Comandos:** `make etl-off-muestra` (baja ~30 MB), `make etl-off-descargar`
  (volcado completo, **pide OK antes**), `make etl-off [OFF_ARCHIVO=...]`,
  `make conflictos` (lista) y
  `python -m etl.conflictos resolver ID a|b [--alias ALIAS]`.
- **Idempotente** (probado: la segunda corrida da 0 cambios) y en streaming: lotes
  de 20 000 filas, `COPY` a una tabla temporal y sentencias por conjuntos.
- El endpoint de admin para conflictos queda para cuando se toque `backend/` (esta
  rama no lo toca).

## 2. Open Food Facts: qué y cuánto

Medido con HEAD sobre `static.openfoodfacts.org/data/`:

| Archivo | Tamaño | Uso |
|---|---|---|
| `en.openfoodfacts.org.products.csv.gz` | **1 537 068 803 B (≈ 1,43 GiB)** | el que usa el ETL |
| `openfoodfacts-products.jsonl.gz` | 13 615 855 563 B (≈ 12,7 GiB) | no hace falta |
| `openfoodfacts-mongodbdump.gz` | 16 645 075 161 B (≈ 15,5 GiB) | no hace falta |
| `food.parquet` (Hugging Face) | 8 053 916 172 B (≈ 7,5 GiB) | alternativa |

**El CSV pesa ~9 veces menos que el JSONL** y trae todo lo que necesitamos
(`code`, `product_name`, `brands`, `quantity`, `image_url`, `countries_tags`); por
eso el plan cambia de «volcado completo (varios GB)» a «CSV (1,4 GiB)». Se actualiza
a diario. Licencia: **ODbL** para la base (atribución y share-alike si se redistribuye
la base) y CC-BY-SA para las imágenes (por eso solo guardamos la URL, nunca el archivo).

### Prueba con una muestra real (primeros 30 MB del CSV, 94 015 filas)

- Tiempo: ~10 s para cargar 94 k filas (≈ 9 000 filas/s) → el completo (estimado en
  ~4,8 M filas por proporción de bytes) tardaría del orden de **10 minutos**.
- Resultado: 93 479 cargados; 536 descartados (494 sin nombre, 41 dígito verificador
  inválido, 1 EAN de balanza). **~51 % no trae `quantity`** en OFF; de los que sí
  traen, el parser entiende el 98 % (el resto son «1/2 gallon», «25 sachets», etc.).
- Espacio por producto: canónico 15 MB + índices 7 MB + `producto_fuentes` 28 MB
  = ~535 B/producto. **Extrapolando a ~4,8 M productos: ≈ 2,5 GB** (estimación
  gruesa: la muestra tiene casi todo EE. UU. y los nombres de otras regiones
  son más largos). Es **5 veces** el tope de 500 MB del plan gratis de Supabase
  (valor a verificar al desplegar).
- Búsqueda por EAN con 93 k filas: **0,29 ms** (Index Scan sobre `ean`).
  No hace falta caché; si se mide una necesidad, `cachetools.TTLCache` detrás de
  una función propia (no `lru_cache` sobre `async`).
- La muestra es sesgada (el CSV viene ordenado por código: empieza por EE. UU.), así
  que **faltan datos reales de Argentina**: solo 3 productos argentinos en la muestra.
  La medición definitiva requiere el volcado completo.

### Decisión pendiente sobre producción (después de cargar todo en local)

1. Cargar todo (~2,5 GB): requiere plan pago de base.
2. **Subconjunto**: `producto_fuentes.datos->'paises'` ya guarda los países de cada
   producto, así que se puede cargar solo lo que tenga `en:argentina` (más países
   vecinos) y con nombre; un `delete`/filtro posterior es simple.
3. **Bajo demanda** (recomendado combinar con 2): si un EAN no está, el backend
   consulta `world.openfoodfacts.org/api/v2/product/{ean}`, lo guarda y lo devuelve.
   La API pide un User-Agent identificable y tiene límites (≈100 lecturas/min por
   producto, a verificar). Falta implementarlo en `backend/`.

### Detalle a resolver en el backend

El backend busca por EAN **exacto**. El ETL guarda EAN-13 (los UPC-A de 12 dígitos
se rellenan con un `0`) y EAN-8 de 8 dígitos. Si el escáner entrega un UPC-A de 12
dígitos, hay que normalizarlo igual (agregar `0`) antes de buscar. Además el producto
sembrado «Fideos tirabuzón» (`7791234567890`) **tiene dígito verificador inválido**:
sigue funcionando (es manual) pero el ETL nunca lo va a emparejar.

## 3. Otras fuentes que van de la mano con OFF

| Fuente | Qué aporta | Licencia | Estado |
|---|---|---|---|
| **SEPA / Precios Claros** (Argentina) | EAN + nombre + marca + presentación + precio por sucursal | CC BY 4.0 (dataset); los términos del sitio hablan de CC BY 2.5 AR | ver §3.1 |
| **Open Prices** (OFF) | precios comunitarios con EAN y local OSM | ODbL (a verificar) | 344 k precios en el mundo; poco útil para AR hoy |
| Open Beauty / Products / Pet Food Facts | EAN de cosmética, hogar, mascotas (lo que OFF no cubre) | ODbL | mismo formato que OFF; el ETL de OFF se reutiliza casi igual. Tamaños de los CSV no medidos (los HEAD no devolvieron largo) |
| GS1 / GEPIR, UPCitemdb, Cosmos (BR) | EAN | propietaria / API paga o con cupo | **descartadas**: términos que no permiten volcado masivo |

### 3.1 SEPA («Precios Claros — Base SEPA»)

Verificado en `datos.produccion.gob.ar/dataset/sepa-precios`:

- **Productos de comercios minoristas grandes**, más de 70 000 productos en todo el
  país, ~12 millones de registros diarios.
- **Un `.zip` por día de la semana** (lunes a domingo), se reescriben semanalmente:
  hay siempre 7 días disponibles. Frecuencia: **diaria**.
- **Licencia: Creative Commons Attribution 4.0** (la ficha del dataset); los
  términos de `preciosclaros.gob.ar` dicen CC BY 2.5 AR para sus contenidos. Ambas
  exigen atribución y permiten uso comercial. Los datos los cargan los comercios y el
  Estado **no garantiza su veracidad** (hay que mostrarlo así).
- **No se verificó**: el tamaño de cada zip (el servidor no devuelve
  `Content-Length`) ni la estructura interna. Según la documentación pública cada zip
  trae por comercio un `comercio.csv`, un `sucursales.csv` (con dirección y
  latitud/longitud) y un `productos.csv` (EAN, descripción, marca, presentación,
  precio). Hay que bajar **un** zip (con tu OK) para confirmar columnas y tamaño.
- **Valor para nosotros:** (a) catálogo con EAN real de góndolas argentinas, que
  complementa a OFF justo donde OFF es flojo; (b) **sucursales con coordenadas** de
  los grandes (Coto, Carrefour, Día, Jumbo...), que sirven para validar/enriquecer
  locales; (c) un «precio de referencia» de cadena, pero **no entra al producto**:
  el Doc 1 dice que los precios los cargan los usuarios.
- **ETL propuesto (`etl/sepa/`)**: bajar un zip, quedarse con EAN → `producto_fuentes`
  (`fuente = 'sepa'`, ya admitida por la migración), con la misma fusión y conflictos.
  Con prioridad menor a OFF salvo que se mida lo contrario, porque en SEPA las
  descripciones son de cada cadena (MAYÚSCULAS, abreviadas) y generarían ruido.
  Como las cadenas repiten el mismo EAN, hay que deduplicar por EAN antes de cargar.

## 4. Catálogo de locales vía OpenStreetMap

### 4.1 Cobertura medida (Overpass, un volcado de Argentina y conteos por zona)

Una consulta de conteos por tipo y **una** de `out center tags` para
`shop=supermarket|convenience` en todo el país (3,9 MB); el análisis por ciudad se
hizo localmente sobre ese volcado (sin más consultas, con User-Agent identificable
y espaciadas; el servidor público llegó a devolver errores por rate limit, no se
insistió).

| Tag `shop=` | Elementos en AR |
|---|---|
| supermarket | 7 255 |
| convenience | 9 070 |
| bakery | 4 845 |
| (greengrocer, butcher, kiosk: la consulta falló por límite del servidor; sin medir) | — |

16 325 locales de super/almacén en el país. Calidad de los tags:

| | nombre | calle | nº de puerta | `brand` | horario |
|---|---|---|---|---|---|
| Argentina (16 325) | 83 % | 35 % | 17 % | 11 % | 8 % |

Por ciudad (cuadro delimitador aproximado del ejido urbano, super + almacén):

| Zona | Locales | con nombre | con calle | con marca |
|---|---|---|---|---|
| CABA | 2 568 | 86 % | 50 % | 25 % |
| AMBA ampliado (incluye CABA) | 5 330 | 84 % | 47 % | 17 % |
| Córdoba | 312 | 83 % | 30 % | 14 % |
| Rosario | 291 | 68 % | 26 % | 7 % |
| Gran Mendoza | 324 | 73 % | 33 % | 10 % |
| S. M. de Tucumán | 82 | 90 % | 42 % | 23 % |
| La Plata | 307 | 76 % | 37 % | 5 % |
| Mar del Plata | 217 | 87 % | 18 % | 8 % |
| Salta | 506 | 98 % | 5 % | 4 % |
| Posadas | 418 | 91 % | 73 % | 2 % |

Marcas principales por cantidad (campo `brand` o, si falta, `name`): Día 482,
Carrefour Express 286 + Carrefour 134 + Market 50, Full 237, La Anónima 159,
Maxikiosco 134, Vea 129, Coto 117, Servicompras 110, Cooperativa Obrera 105,
Disco 76. 2 758 elementos (17 %) **no tienen nombre**.

**Lectura:** las **coordenadas siempre están** (es un mapa) y para ubicar un local
alcanza; el **nombre** está en ~83 %; la **dirección es la parte floja** (35 % con
calle, 17 % con número), así que la dirección no se puede exigir. Capital y AMBA
tienen buena densidad; las otras ciudades tienen una fracción de lo que existe en
la realidad (Córdoba: 312 contra miles de comercios reales), con almacenes de barrio
subrepresentados. Sirve como **base para «locales cerca» y para no empezar de cero**,
no como directorio completo.

### 4.2 ETL de locales propuesto (`etl/osm/`, no implementado)

1. Fuente: **extracto de Geofabrik** (`argentina-latest.osm.pbf`, actualización
   diaria; tamaño no medido) filtrado con `osmium tags-filter` por `shop=supermarket`,
   `shop=convenience` y, si se quiere, `shop=greengrocer|butcher|bakery|kiosk`. Evita
   golpear Overpass; Overpass queda para consultas puntuales chicas.
2. Transformación: `nombre` = `name` (o `brand`; sin ambos → descartar), `direccion` =
   `addr:street` + `addr:housenumber` + `addr:city` si existen, `ubicacion` = punto
   (centroide para áreas), más `osm_id` y marca para trazabilidad.
3. Destino: `locales` con **`verificado = false`**, `creado_por = null`.
   Requiere migración: columnas `osm_tipo`, `osm_id` (únicas) para que la carga sea
   idempotente y se pueda refrescar sin duplicar.
4. **Anti-duplicados**: la misma lógica del alta de locales del corte 5: `pg_trgm`
   sobre el nombre + distancia `ST_DWithin` (config `local_duplicado_metros`). Un local
   OSM que coincide con uno existente no se crea: se le agrega el vínculo OSM.
5. **Riesgo de ruido**: 16 k locales «sin verificar» en un mapa de pocos usuarios
   llenan la pantalla de cosas sin precios. Propuesta: cargarlos, pero la app solo
   muestra locales OSM con al menos un precio o cuando se busca/alta uno cerca.
6. **Licencia ODbL — a decidir con cuidado:**
   - Atribución obligatoria («© colaboradores de OpenStreetMap») visible en la app y
     en la documentación.
   - **Share-alike:** una base derivada que se *redistribuya* debe quedar bajo ODbL.
     Usar los datos para mostrar un mapa o una lista es una «obra producida» (solo
     atribución), pero mezclar locales OSM con locales y datos propios en la misma
     tabla crea una *base derivada*: no pasa nada mientras la base no se publique ni
     se entregue, pero cierra la puerta a regalar/vender un dump de `locales`. Si eso
     importa, mantener los locales OSM identificables (`osm_id`) para poder separarlos.
7. **Google Maps/Places: no.** Sus términos prohíben extraer y guardar sus datos.

## 5. Resumen de decisiones y qué falta

Hecho: ETL de OFF idempotente con tests, tablas de fuentes y conflictos, índice por
EAN, `make etl-off` y `make conflictos`, investigación de fuentes y de locales.

Pendiente (necesita tu decisión o tu OK):

1. **OK para descargar el CSV completo de OFF (1,43 GiB)** y medir el tamaño real.
2. OK para bajar un zip diario de SEPA y confirmar su estructura.
3. Decidir producción: subconjunto por país + carga bajo demanda desde la API de OFF.
4. Si querés el ETL de locales OSM, es un corte aparte (requiere migración en `locales`).
5. `backend/`: endpoint de admin para conflictos, búsqueda por EAN normalizada y
   la carga bajo demanda.
