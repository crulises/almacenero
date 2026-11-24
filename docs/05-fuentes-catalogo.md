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
  menor); sin config rige **`manual > sepa > off`**. Una fuente de menor prioridad solo
  completa campos vacíos; nunca pisa lo manual. Conflictos (lista corta): el **tamaño**
  distinto entre cualquier par de fuentes, y nombre/marca solo contra lo cargado a mano
  (entre SEPA y OFF los nombres siempre difieren —«ACEITE OLIVA NUCETE BOT 250 CC» vs.
  «Aceite de oliva»— y los resuelve la prioridad).
- **Trazabilidad:** cada producto dice de qué fuente es su dato vigente
  (`productos_canonicos.origen`: `manual`, `sepa` u `off`) y `producto_fuentes` guarda
  **todo lo que cada fuente dijo** de ese EAN (con fecha de carga). Un producto puede
  tener varias filas ahí; la canónica sale de la de mayor prioridad.
- **Comandos:** `make etl-off-muestra` (baja ~30 MB), `make etl-off-descargar`
  (volcado completo, **pide OK antes**), `make etl-off [OFF_ARCHIVO=...] [OFF_PAISES=]`
  (por defecto solo Argentina y vecinos), `make etl-sepa-descargar SEPA_URL=...`,
  `make etl-sepa SEPA_ARCHIVOS="a.zip b.zip"`,
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

### Carga completa medida (CSV de 1,43 GiB, 2026-11-16)

Descargado con tu OK (≈ 40 min a ~600 KB/s) y cargado en local:

- **4 916 182 filas leídas → 4 084 328 productos en el catálogo** (el resto:
  831 817 descartadas). Tiempo: **14 min** (≈ 5 800 filas/s) en una Mac, con la base
  en Docker.
- Descartes: 330 479 EAN de balanza, 307 453 sin nombre, 122 164 con dígito
  verificador inválido, 71 721 de largo inválido.
- **Tamaño en la base: 2,4 GB en total.** `productos_canonicos` 1 067 MB (751 de datos +
  316 de índices) y `producto_fuentes` 1 342 MB (el jsonb crudo pesa más que el
  catálogo). Son ≈ 590 B/producto. El tope de 500 MB del plan gratis de Supabase
  (a verificar) queda **5 veces** excedido.
- **Cobertura útil:** solo 1,29 M productos (31 %) tienen tamaño interpretable; 3,0 M
  tienen imagen. Por país (productos con ese país en `countries_tags`, un producto
  puede estar en varios): Francia 1,03 M, EE. UU. 0,90 M, Alemania 0,39 M, España
  0,28 M, Italia 0,25 M. **Argentina: 14 040** (4 985 con tamaño); Argentina + vecinos
  (PY, BR, CL, UY, BO): 61 462. O sea que OFF cubre muy poco de la góndola argentina.
- **Búsqueda por EAN con 4 M de filas: 3,7 ms** en la primera lectura (Index Scan
  sobre `ean`). No hace falta caché.
- **Un subconjunto «Argentina + vecinos»** ocuparía del orden de **35 MB**
  (61 k × 590 B): entra de sobra en el plan gratis.
- Problemas que aparecieron **solo con el volcado real**: caracteres NUL sueltos que
  rompen el lector CSV (corregido y con test) y EAN de 14 dígitos o de largo raro.

### Producción: decidido

Se carga **un subconjunto**: SEPA (Argentina) + OFF de Argentina y vecinos (§2b), 75 MB
medidos. El catálogo completo de OFF (2,4 GB) no entra en el plan gratis. Queda como
opción futura la carga bajo demanda: si un EAN no está, el backend lo busca en la API de
OFF (`world.openfoodfacts.org/api/v2/product/{ean}`, con User-Agent identificable y
respetando límites a verificar), lo guarda con `origen = 'off'` y lo devuelve; cubriría
el mundo sin almacenarlo todo. Falta implementarlo en `backend/`.

### Detalle de diseño: relleno del EAN al escanear y buscar

**Decisión de diseño:** el mismo relleno que usa el ETL debe aplicarse en el backend (o en
la app) al leer un código, antes de comparar con la base: un UPC-A de 12 dígitos pasa a
EAN-13 con un `0` adelante (equivalentes por estándar GS1), y un EAN-8 se busca tal cual.
Hoy el backend busca por EAN **exacto**. El ETL guarda EAN-13 (los UPC-A de 12 dígitos
se rellenan con un `0`) y EAN-8 de 8 dígitos. Si el escáner entrega un UPC-A de 12
dígitos, hay que normalizarlo igual (agregar `0`) antes de buscar. Además el producto
sembrado «Fideos tirabuzón» (`7791234567890`) **tiene dígito verificador inválido**:
sigue funcionando (es manual) pero el ETL nunca lo va a emparejar.

## 2b. Estrategia de catálogo acordada: SEPA para Argentina, OFF para los vecinos

- **SEPA** (`etl/sepa/`) es la fuente principal de Argentina: se puede re-correr con el
  zip del día (idempotente). Solo se usa `productos.csv` (EAN, nombre, marca,
  presentación); **los precios de SEPA no se cargan** (los precios los cargan los
  usuarios). Agrupa millones de filas por EAN y elige la variante más frecuente;
  pasa los nombres de MAYÚSCULAS a «Título».
- **OFF** (`make etl-off`) se carga **solo con Argentina y sus vecinos** (AR, PY, BR, CL,
  UY, BO) por defecto; `OFF_PAISES=` (vacío) carga todo el mundo.
- **Medido con el zip de SEPA del domingo 15/11 + OFF filtrado:**

| | Productos |
|---|---|
| SEPA (EAN válidos, deduplicados) | 75 744 |
| OFF (AR + vecinos) | 61 462 (4 854 también en SEPA) |
| **Catálogo resultante** (EAN únicos, + 2 manuales) | **132 354** (75 744 SEPA + 56 608 OFF + 2 manuales) |
| EAN de SEPA que también están en OFF (cualquier país, OFF completo) | 9 316 |
| Conflictos pendientes tras la carga (todos de tamaño) | 157 |

- **¿Los 14 040 argentinos de OFF están cubiertos por SEPA? No: solo 4 527 (32 %).**
  Los otros **9 513** son productos que OFF conoce y SEPA no (SEPA son solo cadenas
  grandes; OFF trae también marcas de góndola de comercios chicos, importados, etc.).
  Por eso conviene cargar OFF-Argentina además de SEPA, no en lugar de.
- **Espacio: 75 MB** (catálogo + crudo por fuente, con índices) para esos 132 354
  productos. **No son los 35 MB** que dije antes (eran solo los 61 k de OFF sin SEPA):
  sigue siendo ~13 % del tope de 500 MB (a verificar) y deja mucho margen. Si hiciera
  falta, lo más pesado es el `datos` jsonb crudo, que se puede recortar.
- Descartes de SEPA (en filas): 252 816 de EAN de balanza, 170 402 con `productos_ean=0`
  (sin EAN real), 1 292 con dígito verificador inválido; además 1 zip interno vacío.
- Tiempo de SEPA: 2,5 min para el zip de 330 MB (14,7 M filas).
- **Frescura:** SEPA se publica a diario. Con un zip por semana (o el día más completo)
  alcanza para un catálogo; la idempotencia hace que repetirlo solo toque lo que cambió.
  Un zip de otro día puede tener otros comercios: conviene correr los 7 días de vez en
  cuando para cubrir más EAN.

## 2c. La fuente `curado` (corte 17)

No es una fuente nueva de datos sino un **formato de intercambio**: el extracto normalizado de OFF
y SEPA que el dueño arma en su máquina y se importa donde haga falta (otra base, producción).
Prioridad `manual > curado > sepa > off`. Detalle en `docs/04` §10-B.

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
- **Medido con el zip del domingo 2026-11-15** (330 MB, descarga completa y válida;
  los de viernes y martes quedaron truncados: el servidor corta conexiones largas y no
  admite reanudar, así que hay que reintentar). Es un **zip de zips**: uno por
  comercio (16 en ese archivo), y cada uno con `comercio.csv`, `sucursales.csv` y
  `productos.csv`, separados por `|`.
  - `productos.csv`: `id_producto` (**el EAN**; `productos_ean` es solo un flag 1/0),
    descripción, `cantidad_presentacion` + `unidad_medida_presentacion`, marca, precio
    de lista, precio de referencia y promos. **14,7 M de filas, 81 325 EAN distintos**
    (76 202 válidos; 398 k filas son EAN de balanza y 7 k tienen dígito inválido).
  - `sucursales.csv`: nombre, tipo, calle, número, **latitud/longitud**, localidad,
    provincia (código ISO, p. ej. `AR-N` = Misiones), horarios por día. 3 060
    sucursales, 97 % con coordenadas.
  - Suciedad real: 9 de 16 archivos con BOM, caracteres NUL, unidades inconsistentes
    (`UNI`, `GR`, `gr.`, `grm`, `cm3`, `cmq`...), 205 k filas sin marca, nombres en
    mayúsculas y abreviados («ACEITE OLIVA NUCETE EXTRA VIRGEN BOT 250 CC»).
- **Valor para nosotros:** (a) catálogo con EAN real de góndolas argentinas, que
  complementa a OFF justo donde OFF es flojo; (b) **sucursales con coordenadas** de
  los grandes (Coto, Carrefour, Día, Jumbo...), que sirven para validar/enriquecer
  locales; (c) un «precio de referencia» de cadena, pero **no entra al producto**:
  el Doc 1 dice que los precios los cargan los usuarios.
- **ETL propuesto (`etl/sepa/`)**: bajar un zip, quedarse con EAN → `producto_fuentes`
  (`fuente = 'sepa'`, ya admitida por la migración), con la misma fusión y conflictos.
  Con prioridad menor a OFF salvo que se mida lo contrario, porque en SEPA las
  descripciones son de cada cadena (MAYÚSCULAS, abreviadas) y generarían ruido.
  Como las cadenas repiten el mismo EAN (14,7 M de filas para 81 k EAN), hay que
  deduplicar por EAN antes de cargar. Es **el aporte más grande para Argentina**:
  81 k EAN contra 14 k de OFF; falta medir cuántos se solapan con OFF (el ETL de
  SEPA lo mostraría como conflictos y completados).
- **Sucursales de Misiones en SEPA: solo 17** (13 en Posadas; California
  Supermercados, Farmacity, Changomas, La Anónima), contra 1 043 en OSM: para locales
  de Misiones SEPA casi no sirve.

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

### 4.1.b Misiones: cómo vienen los registros y cuántos están «completos»

1 044 supermercados y almacenes (`shop=supermarket|convenience`). Cada registro de OSM
es un nodo con **coordenadas, fecha de la última edición, usuario que lo editó** y un
conjunto libre de etiquetas. Ejemplo real (un registro completo):

```json
{"tipo": "node", "id": 6114354371, "editado": "2020-04-08",
 "lat": -27.357982, "lon": -55.9222557,
 "tags": {"shop": "convenience", "name": "Autoservicio La Esperanza",
          "addr:street": "Avenida Urquiza", "addr:housenumber": "4803",
          "addr:city": "Posadas", "addr:province": "Misiones", "addr:country": "AR"}}
```

Etiquetas más usadas (de 1 044): `name` 901, `addr:street` 638, `addr:city` 546,
`addr:postcode` 459, `addr:housenumber` 237, `opening_hours` 88, `phone` 53,
`operator` 25, `brand` 17, medios de pago (`payment:*`) ~13, `website` 10,
`check_date` 8 (solo 8 registros dicen cuándo se verificó por última vez).

| Criterio de «completo» | Registros | De esos, editados desde 2023 |
|---|---|---|
| con nombre | 901 | 242 |
| nombre + calle | 599 | 153 |
| **nombre + calle + número** | **222** | 46 |
| nombre + calle + número + localidad | 187 | 34 |
| nombre + calle + (horario o teléfono) | 103 | 35 |

**«Sigue funcionando hoy» no se puede saber desde OSM.** Si un comercio cierra, OSM
suele sacarle el `shop` (queda `disused:shop`) y deja de aparecer, pero casi nadie lo
mantiene al día: la mayoría de los registros se cargó en 2016-2019 (221 en 2018, 143 en
2019) y solo 8 tienen `check_date`. Lo único que lo confirma es que **un usuario cargue un
precio ahí**. Propuesta: cargar los 222 con nombre + calle + número como
`verificado = false` («candidatos»), y que la primera carga de precio de un usuario sea
la señal de que sigue abierto; no mostrar como «vigente» lo que nadie confirmó.

### 4.1.c Atribución: qué hay que hacer y si vale la pena

**Qué exige cada fuente** (y qué hay que mostrar):

| Fuente | Licencia | Qué hay que hacer |
|---|---|---|
| OpenStreetMap (locales) | ODbL 1.0 | Mostrar «© colaboradores de OpenStreetMap» con enlace a `openstreetmap.org/copyright`; decir que los datos están bajo ODbL |
| Open Food Facts (productos) | ODbL (base) + DbCL (contenidos); imágenes CC BY-SA | Mostrar «Datos: Open Food Facts (openfoodfacts.org), ODbL»; las imágenes se enlazan, no se copian |
| SEPA / Precios Claros | CC BY 4.0 | Mostrar «Fuente: Secretaría de Comercio de la Nación, Precios Claros (SEPA)» y que se modificó (normalizado) |

**El procedimiento es el mismo para las tres y se hace una sola vez:** una pantalla
«Acerca de / Datos y licencias» en la app (y la misma sección en el README) con esas tres
líneas y sus enlaces. En la pantalla del mapa, si se muestran locales de OSM, además un
texto chico «© OpenStreetMap» en una esquina (es el uso habitual). No hay trámite, registro
ni aviso a nadie. **Costo: una pantalla de texto.**

**Como OFF y SEPA ya obligan a tener esa pantalla, agregar OSM cuesta una línea más.**
No hace falta pedir permiso. El único tema de fondo es el *share-alike* de la ODbL:
- Mostrar locales en un mapa o una lista es una «obra producida»: solo atribución.
- Si algún día se **distribuye o publica la base** (un dump, una API abierta), la parte
  derivada de OSM debe seguir bajo ODbL. Con locales de OSM mezclados con los propios en la
  misma tabla, eso obliga a poder separarlos: por eso el ETL guarda `osm_tipo` + `osm_id`.
- Corregir un dato de OSM en nuestra base (un `verificado = true` con nombre arreglado) no
  genera obligación mientras no distribuyamos la base. Lo ideal para devolverle algo a OSM
  es corregir el dato **en OSM**, pero no es obligatorio.

**¿Vale la pena para Misiones?** Mi lectura, con datos: **sí, pero chico y con criterio**.
- A favor: la atribución ya la necesitás por OFF y SEPA (costo marginal ≈ 0); 222
  comercios de barrio con nombre, calle y número en Misiones son un punto de partida
  que ninguna otra fuente da (SEPA tiene 17 sucursales ahí); evitás que cada usuario
  tenga que crear el local a mano; y el diseño (`verificado=false`, `osm_id`) deja
  agregar otras provincias o países cambiando solo el filtro geográfico.
- En contra: 222 es poco, la mayoría de los datos tiene 5-8 años (no hay garantía de que
  sigan abiertos), y el ruido de una lista con comercios cerrados cuesta confianza.
- **Recomendación (decisión final: se pide nombre + calle, sin número; ver §4.2):** hacer el ETL de locales con el criterio «nombre + calle + número»
  y por provincia (parámetro), arrancando por Misiones, y tratar esos locales como
  candidatos hasta que alguien cargue un precio. Si después de probarlo en Posadas
  resultan pocos útiles, se apaga sin costo (se borran por `osm_id`).

### 4.2 ETL de locales (`etl/osm/`, `etl/sepa/locales.py`): implementado

Migración `20261119000001_locales_fuentes.sql`: `locales.fuente` (`manual`|`osm`|`sepa`:
cómo nació el local) y la tabla `local_fuentes (local_id, fuente, ref, datos jsonb,
cargado_en)` con `unique (fuente, ref)`. `ref` es `node/123` o `way/456` en OSM, y
`id_comercio-id_bandera-id_sucursal` en SEPA. Un local puede tener varios vínculos (el
mismo comercio en OSM y en SEPA); borrar los locales de una fuente es
`delete from locales where fuente = 'osm'` (cascada a `local_fuentes`).

1. **Fuente OSM:** extracto de Geofabrik `argentina-latest.osm.pbf` (**~436 MB**; Geofabrik
   no parte Argentina por provincia), `make etl-osm-descargar`. Se lee con `pyosmium`
   (extra `etl` de `backend/pyproject.toml`; no lo usa el backend) y se queda con
   `shop=supermarket|convenience`. La **provincia es un parámetro** (`PROVINCIA=misiones`,
   slug o código `AR-N`): se recorta con el límite administrativo de OSM de ese código
   (`ISO3166-2`), que viene en el mismo extracto, y el recorte lo hace PostGIS
   (`st_covers`). Las coordenadas de un edificio mapeado como camino son el centro de su
   caja.
2. **Criterio de «completo»:** `name`, `addr:street` y coordenadas. El número de puerta
   no hace falta (se pule después). `direccion` = calle + número (si hay) + ciudad (si hay).
3. **Fuente SEPA:** `sucursales.csv` de cada comercio del zip diario. Nombre = bandera
   (`comercio_bandera_nombre`) + nombre de la sucursal si dice algo («Coto Acassuso»);
   si es genérico («Sucursal 3», «Local 12») queda solo la bandera. Mismo criterio:
   nombre + calle + coordenadas válidas (dentro de Argentina; descarta 0,0 y vacías).
   `--provincia` filtra por `sucursales_provincia` (`AR-N`); sin parámetro, todo el país.
4. **Destino y trazabilidad:** `locales` con `verificado = false`, `creado_por = null`,
   `fuente = 'osm'|'sepa'`, más la fila en `local_fuentes` con el dato crudo (etiquetas
   de OSM, campos de SEPA). **Idempotente:** si el `(fuente, ref)` ya está vinculado solo
   se refresca el crudo (el local no se toca: lo puede haber corregido el admin).
5. **Anti-duplicados:** la misma lógica del alta de locales del corte 5: nombre parecido
   (`pg_trgm`, config `local_duplicado_similitud`, 0,8) a menos de
   `local_duplicado_metros` (50 m). Si ya existe, no se crea otro: se le agrega el
   vínculo a esta fuente (por eso cargar SEPA y OSM en cualquier orden no duplica).
   Diferencia con el backend: acá se compara sin acentos (`unaccent`).
6. **Escala:** se procesa local por local (miles por provincia, segundos). Para todo el
   país o el mundo conviene pasar a staging + SQL por conjuntos como en el catálogo.
7. **Resultado en Misiones** (extracto de Geofabrik del 2026-11-18, corrida del
   2026-11-19, 23 s):

   | | OSM (`make etl-osm PROVINCIA=misiones`) | SEPA (`make etl-sepa-locales PROVINCIA=misiones`) |
   |---|---|---|
   | Registros en la provincia | 1 021 (16 364 en el país) | 3 060 sucursales leídas (todo el país); 17 en AR-N |
   | Descartados sin nombre | 140 | 0 |
   | Descartados sin calle | 288 | 0 |
   | **Locales nuevos** | **592** | **17** |
   | Vinculados a uno existente | 1 (el mismo comercio como `node` y como `way`) | 0 |
   | Con número de puerta | 280 | 17 |

   Entre OSM y SEPA no hubo ningún duplicado en Misiones (las 17 sucursales de SEPA son
   grandes cadenas de Posadas que OSM no tiene con ese nombre a menos de 50 m). Recargar
   da 0 nuevos y refresca los 593 + 17 vínculos. Total en la base local: 611 locales sin
   verificar (592 OSM, 17 SEPA y 2 manuales de prueba).
8. **Riesgo de ruido:** locales «sin verificar» llenan el mapa con comercios que quizá
   cerraron. Propuesta (a decidir en la app, no acá): mostrar los de OSM/SEPA con una
   marca de «sin confirmar» y que el primer precio cargado ahí los confirme.
9. **Licencia ODbL — a decidir con cuidado:**
   - Atribución obligatoria («© colaboradores de OpenStreetMap») visible en la app y
     en la documentación.
   - **Share-alike:** una base derivada que se *redistribuya* debe quedar bajo ODbL.
     Usar los datos para mostrar un mapa o una lista es una «obra producida» (solo
     atribución), pero mezclar locales OSM con locales y datos propios en la misma
     tabla crea una *base derivada*: no pasa nada mientras la base no se publique ni
     se entregue, pero cierra la puerta a regalar/vender un dump de `locales`. Si eso
     importa, mantener los locales OSM identificables (`osm_id`) para poder separarlos.
10. **Google Maps/Places: no.** Sus términos prohíben extraer y guardar sus datos.

### 4.3 Atribuciones: texto literal para la pantalla «Atribuciones» de la app

Texto listo para copiar (español) y los enlaces que lo acompañan. Cada bloque es un
ítem de la pantalla; los enlaces van como enlaces tocables y, si hay una versión
impresa/exportada, con la URL completa escrita. Las licencias y versiones se
verificaron en las páginas de cada proyecto el 2026-11-19; las fuentes no fijan una
redacción exacta, solo qué nombrar y a quién enlazar (la de SEPA es la del propio
dataset): **si un texto cambia, que sea para nombrar más, nunca menos.**

**Encabezado de la pantalla:** «Almacenero usa datos abiertos de estas fuentes. Gracias
a quienes los mantienen.»

1. **OpenStreetMap** (locales; se muestra en la pantalla de locales/mapa, además de
   en «Atribuciones»; en el mapa alcanza con «© OpenStreetMap»):
   - Texto: «Datos de locales: © colaboradores de OpenStreetMap. Disponibles bajo la
     Open Database License (ODbL) 1.0.»
   - Enlaces: «© colaboradores de OpenStreetMap» → https://www.openstreetmap.org/copyright
     · «ODbL 1.0» → https://opendatacommons.org/licenses/odbl/1-0/
   - Si algún día se publica un mapa con teselas de OSM, se suma el mismo «©
     OpenStreetMap contributors» sobre el mapa (guía:
     https://osmfoundation.org/wiki/Licence/Attribution_Guidelines).
2. **Open Food Facts** (productos: nombre, marca, tamaño; e imágenes si se muestran):
   - Texto: «Datos de productos: Open Food Facts (openfoodfacts.org), una base colaborativa
     disponible bajo la Open Database License (ODbL) 1.0; sus contenidos individuales,
     bajo la Database Contents License (DbCL) 1.0. Las imágenes de productos se
     publican bajo Creative Commons Atribución-CompartirIgual (CC BY-SA) 3.0 y son de
     sus autores; Almacenero solo las enlaza.»
   - Enlaces: «Open Food Facts» → https://openfoodfacts.org · «ODbL 1.0» →
     https://opendatacommons.org/licenses/odbl/1-0/ · «DbCL 1.0» →
     https://opendatacommons.org/licenses/dbcl/1-0/ · «CC BY-SA 3.0» →
     https://creativecommons.org/licenses/by-sa/3.0/ · términos →
     https://world.openfoodfacts.org/terms-of-use
   - Si una pantalla muestra un producto y su imagen, junto a la imagen va «Imagen:
     Open Food Facts, CC BY-SA 3.0» enlazada a la ficha del producto
     (`https://world.openfoodfacts.org/product/<ean>`).
3. **SEPA / Precios Claros** (catálogo de Argentina y sucursales de cadenas):
   - Texto: «Datos de productos y sucursales de Argentina: Secretaría de Comercio de la
     Nación, Sistema Electrónico de Publicidad de Precios Argentinos (SEPA, «Precios
     Claros»), licencia Creative Commons Atribución 4.0 Internacional (CC BY 4.0). Los
     datos fueron normalizados y combinados por Almacenero.»
   - Enlaces: «SEPA» → https://datos.produccion.gob.ar/dataset/sepa-precios ·
     «CC BY 4.0» → https://creativecommons.org/licenses/by/4.0/deed.es
   - El «fueron normalizados» cumple el requisito de CC BY de indicar que se
     modificó el material.
4. **Pie de la pantalla:** «Los precios que ves los cargan personas como vos; no
   provienen de estas fuentes.» (los precios de SEPA no se cargan, ver §3.1).

Qué datos cae bajo cada texto (para saber cuándo mostrarlo): `locales.fuente = 'osm'` o
vínculo `local_fuentes.fuente = 'osm'` → bloque 1; `productos_canonicos.origen` o
`producto_fuentes.fuente = 'off'` → bloque 2; `'sepa'` (productos o locales) → bloque 3.
La pantalla puede mostrar los tres siempre (más simple y siempre correcto).

## 5. Resumen de decisiones y qué falta

Hecho: ETL de OFF (filtrable por país) y de SEPA, idempotentes y con tests; tablas de
fuentes y conflictos; trazabilidad por `origen` + `producto_fuentes`; índice por EAN;
`make etl-off`, `make etl-sepa`, `make conflictos`; investigación de fuentes y de locales.

Hecho además: ETL de locales de OSM (Misiones) y de sucursales de SEPA, con
trazabilidad en `local_fuentes`, anti-duplicados y atribuciones literales (§4.2, §4.3).

Pendiente:

1. Pantalla «Atribuciones» en la app con los textos de §4.3.
2. Decidir en la app cómo se muestran los locales sin verificar (§4.2, punto 8).
3. `backend/`: normalizar el EAN leído (UPC-A → EAN-13) antes de buscar; endpoint de admin
   para conflictos; carga bajo demanda desde la API de OFF.
4. Medir en el celular qué entrega `mobile_scanner` para UPC-A.
5. Más provincias: `make etl-osm PROVINCIA=<otra>` y `make etl-sepa-locales`; para todo
   el país o el mundo, pasar la fusión de locales a SQL por conjuntos.
