# Plan 0.1 (antes «v0.0.2»)

> Este plan es el del release **0.1.x** (cerrado con el corte 20). Se llamó «v0.0.2» cuando se escribió;
> el archivo se renombró a `04-plan-v0.1.md`. Dentro del texto, «v0.0.1» y «v0.0.2» son nombres
> históricos de planes. Siguientes: `04-plan-v0.2.md` en adelante (`docs/10-roadmap.md`).

Estado: **plan aprobado, con decisiones abiertas al final**. Parte de v0.0.1
cerrada y probada en un celular real (escanear, cargar precio, karma,
historial). Ante una duda de comportamiento gana el Doc 1; ante una duda técnica,
el Doc 2. **El Doc 1 no cambia**: la regla «solo el admin crea locales» sigue
vigente; el alta abierta a cualquier usuario es solo una comodidad de prueba
(ver §2). Hay que actualizar la sección de alcance de `CLAUDE.md` al arrancar.

## Objetivo de v0.0.2

Pasar de «un solo local, a mano» a «datos reales y cargables en cualquier
comercio»: poder crear un local donde estás parado, cargar solo si estás cerca,
contar con un catálogo de verdad y ver precios vigentes con su frescura. Y dejar
la puerta cerrada al spam sin esperar al deploy.

Fuera de v0.0.2 (sigue igual): validación colaborativa y cola, gamificación,
offline, iOS, OAuth, pesables/genéricos.

## Cortes (cada uno, su rama y su PR)

| # | Corte | Depende de | Tamaño |
|---|-------|-----------|--------|
| 5 | Roles + alta de local + «locales cerca» | — | medio |
| 6 | Geofence al cargar un precio | 5 | medio |
| 7 | ETL de Open Food Facts | — (en paralelo a 5/6) | medio |
| 8 | **Precios vigentes por local: lista con frescura + mapa** (adelantado: va antes que 6) | — | medio |
| 9 | Anti-spam (invitaciones, rate limit, límites por usuario) | 5 | medio |
| 10 | Preparar release: firma del APK y guía de deploy | — | chico |
| 12 | **Moderación: escalera por karma negativo y baja de cuentas** (§9) | 9, 11 | medio |
| 11 | **Panel web de admin** (front chico con nginx + endpoints `/v1/admin`), en paralelo, sin tocar la app | 5 | grande |
| 13-18 | **Calidad del catálogo, moderador y sugerencias, CSV curado, ETL desde el panel** (§10, acordado) | 7, 11 | ver §10 |

El ETL (7) toca solo `etl/` y el Makefile, así que puede correr en paralelo con
5 y 6. Los demás van de a uno.

## 1. Roles y permisos (corte 5)

Hoy no hay roles: todos los usuarios pueden todo lo que el backend expone.
Propuesta mínima, sin sobrearmar:

- `usuarios.rol`: `usuario` (por defecto) o `admin`. Un `check` en Postgres
  limita los valores (integridad en la base).
- **El rol no se puede cambiar por la API.** Se asigna con SQL o un target del
  Makefile (`make admin ALIAS=...`). Así ningún bug de endpoint escala
  privilegios. Es la misma idea que el trigger del karma.
- En el backend, una dependencia `exigir_admin` (junto a `current_user`) para los
  endpoints de administración. Todo lo demás exige solo estar autenticado.
- Más adelante (no ahora) puede aparecer `moderador` para la validación
  colaborativa; el `check` se amplía con una migración.

| Acción | Usuario (anónimo o no) | Admin |
|--------|:---:|:---:|
| Leer catálogo, precios y locales | sí | sí |
| Cargar precio (cerca de un local) | sí | sí |
| Crear un local donde está parado | sí, queda **sin verificar** | sí |
| Verificar / corregir / fusionar / borrar locales | no | sí |
| Corregir productos del catálogo | no | sí |
| Cambiar configuración (`config`) | no | sí |
| Emitir invitaciones | no | sí |

### ¿Alcanza una columna, o hace falta un ACL más robusto?

Estudio corto, para decidir con criterio y no por moda.

**Lo que el producto va a necesitar** (según el Doc 1):

- Un administrador (hoy).
- Capacidades que **dependen del karma** («los de karma bajo entran a validación
  con más lupa», el que valida bien gana peso). Eso es una regla sobre un
  *atributo* del usuario, no un rol.
- Probablemente un **moderador** que valide o resuelva conflictos.
- Quizás permisos **acotados a un local o zona** (p. ej. alguien de confianza
  para un barrio). Es lo único que una columna simple no puede expresar.

**Opciones:**

| Opción | Qué es | Cuándo tiene sentido |
|--------|--------|----------------------|
| A. Columna `rol` | Un valor por usuario, comprobado en el backend | Pocos roles, sin alcance por local. **Hoy.** |
| B. RBAC con tablas | `roles`, `permisos`, `rol_permisos`, `usuario_roles` (con `local_id` opcional como alcance) | Varios roles, permisos editables o con alcance. Probablemente v0.1+. |
| C. Motor externo (Casbin, Oso, Cerbos, SpiceDB) | Políticas declarativas o servicio aparte | Muchos recursos y reglas cruzadas. Excesivo para un proyecto de hobby. |
| D. RLS de Postgres | Políticas en la base | **No encaja**: el cliente nunca habla con la base y la lógica de negocio vive en el backend (CLAUDE.md). |

**Recomendación:** empezar con A, pero **diseñando para migrar a B sin tocar los
endpoints**:

- Los endpoints nunca preguntan «¿es admin?». Preguntan por una **capacidad con
  nombre**: `puede(usuario, "local.verificar")`. Hay un solo módulo del backend
  que traduce rol → capacidades.
- Hoy ese módulo es un diccionario en código (`admin` tiene todas, `usuario` las
  básicas). Migrar a tablas es cambiar **un módulo y una migración**, no cada
  endpoint.
- Las reglas por karma son lógica de negocio en ese mismo módulo, con umbrales en
  `config` (p. ej. `karma_minimo_para_validar`).

**Cuándo pasar a B:** cuando aparezca el segundo rol con privilegios (moderador),
un permiso con alcance por local, o la necesidad de editar permisos sin
desplegar. Hasta entonces B sería sobreingeniería.

## 2. Alta de local por cualquier usuario (corte 5)

Mientras no haya forma de crear usuarios con rol (hoy todos son anónimos), la
regla del Doc 1 («solo el admin crea locales») impediría probar. **Solución: un
interruptor de configuración**, `config.alta_locales_abierta`, en `true` durante
las pruebas. Con `false`, solo un admin crea locales, como dice el Doc 1. No se
cambia el Doc 1: es una comodidad temporal y se apaga cuando haya setup de
usuarios.

Diseño:

- `locales.verificado boolean not null default false`. El local creado por un
  usuario nace **sin verificar** pero usable, así no se frena la carga. El admin lo
  verifica, corrige o fusiona con un duplicado.
- `POST /v1/locales` con nombre y la ubicación **actual** (lat/lng). La
  ubicación sale del GPS, no se tipea: es lo que da sentido al geofence.
- **Anti-duplicados, sin bloquear.** Hay locales contiguos legítimos (dos
  kioscos pegados), así que la distancia sola **no** puede impedir el alta. Cómo
  se resuelve:
  - Al crear, la app muestra los locales cercanos (~50 m) y pregunta «¿es alguno
    de estos?», con una salida siempre visible: «Es otro local, crear nuevo».
  - El backend **solo bloquea** el caso casi seguro de duplicado: **mismo nombre
    (normalizado, comparado con similitud de texto) a muy poca distancia**. Ahí
    responde con el local existente en vez de crear.
  - Para la similitud se usa la extensión `pg_trgm` de Postgres.
- **Límite por usuario:** 50 locales nuevos por día al principio. El valor vive
  en `config` (`max_locales_por_dia`) y se baja cuando haya más usuarios.
- `GET /v1/locales/cerca?lat=&lng=` ordenado por distancia (PostGIS,
  `ST_DWithin` + `ST_Distance` sobre el índice GiST que ya existe).
- La app detecta el local más cercano dentro del geofence; si no hay ninguno,
  ofrece «Crear local aquí». Recuerda el último local usado.
- Los locales sin verificar se muestran marcados, para no mezclarlos con los
  confirmados.

El seed deja de tener un único local con coordenadas de ejemplo: el local de
desarrollo pasa a tener las coordenadas reales de quien prueba (o se crea desde
la app).

## 3. Geofence (corte 6)

- La app pide permiso de ubicación (`ACCESS_FINE_LOCATION`) con un paquete de
  geolocalización y manda `lat`, `lng` y `precision_m` con cada carga.
- El backend (negocio, no Postgres) calcula la distancia al local con PostGIS y
  rechaza si supera `config.geofence_metros` (150 m) con un error que la app
  explica: «Estás a 480 m del local».
- Si la precisión del GPS es peor que un umbral, se pide reintentar en vez de
  rechazar a ciegas.
- **Límite conocido:** la ubicación la informa el celular; un teléfono con
  ubicación simulada puede mentir. No hay defensa perfecta; se mitiga con
  reputación y attestation (§6), no con más geofence.
- Leer precios sigue sin pedir ubicación (Doc 1).
- Para probar en el emulador: `adb emu geo fix <lng> <lat>`.
- **Implementado (corte 6):** `POST /v1/precios` exige `lat`, `lng` y `precision_m`;
  403 con `detail.codigo` = `fuera_de_rango` (con `distancia_m` y `radio_m`) o
  `precision_baja` (umbral `config.geofence_precision_max_m`, 100 m). La app toma
  una ubicación fresca al enviar y explica el rechazo.

## 4. Catálogo real: un ETL por fuente (corte 7)

### Principio: un ETL por fuente, un solo destino

- Cada fuente tiene su propio pipeline (`etl/off/`, `etl/<otra-fuente>/`, ...)
  con su lógica propia. No se fuerza una abstracción común: es más simple y más
  flexible.
- Todos escriben al mismo catálogo (`productos_canonicos`) a través de una capa
  mínima compartida (conexión, *upsert*, normalización de tamaño/unidad). Target
  del Makefile por fuente (`make etl-off`).
- **Idempotentes**: correrlos de nuevo no duplica ni pisa lo que cargó el admin.

### Primera fuente: Open Food Facts, todo el mundo

- Fuente: el **volcado completo** de OFF (no la API producto por producto), sin
  filtrar por país: en un local de barrio puede haber productos importados.
  El archivo pesa varios GB: se baja a `etl/data/` (ignorado por git) y se procesa
  en streaming. **La descarga grande requiere tu OK** cuando llegue el momento.
- Pasos: validar el EAN (largo y dígito verificador) → normalizar `quantity` a
  `tamano_valor` + `tamano_unidad` → *upsert* por EAN con `origen = 'off'`.
- Imagen: URL de OFF, no se guarda el archivo (Doc 2).
- Reporte al final: cuántos se cargaron y cuántos se descartaron, y por qué.
- Tests sobre la normalización, que es donde se ensucian los datos.

### Tamaño: medir antes de prometer

Cargar «todo» son **millones de filas** (el número exacto se mide con el
volcado). En local no hay problema. En producción hay que tener en cuenta que el
plan gratis de Supabase tiene un tope de almacenamiento de base de datos
(verificar el valor vigente), y el catálogo completo con índices podría pasarlo.
Plan: **cargar todo en local, medir el tamaño real** y recién ahí decidir entre:

1. Pagar un plan con más espacio.
2. Cargar completo solo lo «útil» (con nombre y tamaño utilizables) y el resto
   bajo demanda.
3. **Carga bajo demanda:** si un EAN no está en el catálogo, el backend lo busca
   en la API de OFF, lo guarda y lo devuelve. Cubre todo el mundo sin almacenar
   todo. Se puede combinar con la carga masiva de la región.

### Búsqueda por EAN y caché

- **Ya está indexado:** `productos_canonicos.ean` es `unique`, y esa restricción
  crea un índice B-tree. Buscar por EAN es una lectura por índice, del orden del
  milisegundo, aun con millones de filas.
- **Caché: no al principio.** Con ese índice probablemente no haga falta. Se mide
  primero. Dos advertencias para cuando llegue el momento:
  - `@lru_cache` **no funciona con funciones `async`** (cachea el *coroutine*,
    que solo se puede esperar una vez). Para cachear en el backend async se usa
    `cachetools.TTLCache` (acotado y con vencimiento) detrás de una función
    propia.
  - La caché en memoria es por proceso: con varios workers cada uno tiene la
    suya. Si hace falta compartirla, el siguiente paso es Redis. Se cachea el
    **producto** (casi no cambia), nunca los precios.

### Varias fuentes y conflictos

Cuando dos fuentes (o una fuente y el admin) discrepan sobre un EAN, no se pisa
nada en silencio: queda en una **lista corta para revisar a mano**.

- `producto_fuentes`: el dato crudo de cada fuente por EAN (`ean`, `fuente`,
  `datos` jsonb, `cargado_en`). El catálogo canónico se arma desde acá, con un
  **orden de prioridad de fuentes** configurable.
- `conflictos_catalogo`: `ean`, `campo`, valor y fuente A, valor y fuente B,
  `estado` (pendiente / resuelto), quién lo resolvió y cuándo.
- **Qué cuenta como conflicto** (para que la lista siga corta): tamaño o unidad
  distintos tras normalizar, y marca o nombre **muy** distintos (por similitud de
  texto). Las diferencias de forma (mayúsculas, acentos, «Aceite Girasol» vs.
  «aceite de girasol») **no** son conflicto.
- Un campo que el admin resolvió queda **bloqueado**: ningún ETL lo vuelve a
  tocar.
- Revisión en v0.0.2: endpoint de admin y `make conflictos` en consola. Una
  pantalla en la app, más adelante.

### Otras fuentes a investigar (cada una, su propio ETL)

- Datos abiertos de precios del Estado argentino (SEPA / «Precios Claros»):
  traen productos con EAN y precios por comercio. Hay que revisar formato,
  licencia y frecuencia de actualización antes de decidir.
- Aportes manuales del admin.
- **Locales de cadenas conocidas (seed de ubicaciones):** fuente candidata
  OpenStreetMap (Overpass API: `shop=supermarket`, `brand=...`, por país o zona).
  Es abierta (licencia ODbL: exige atribución), a diferencia de scrapear Google
  Maps, que viola sus términos, o de la Places API, que es paga y prohíbe guardar
  los datos. Entrarían como locales `verificado = false` hasta que un admin los
  confirme, con su propio ETL por fuente. Investigar cobertura real antes de
  prometer nada. Complemento: los localizadores de tiendas que publican las
  propias cadenas (revisar sus términos).

El «alta mínima de producto» desde la app (para un EAN que ninguna fuente cubra)
queda fuera de v0.0.2.

## 5. Precios vigentes, frescura y mapa (corte 8, adelantado)

Un producto va a tener varios «precios activos» (uno por local), así que la lista
con la frescura de cada uno pasa a ser lo central de la ficha.

- `GET /v1/productos/{ean}/precios/vigentes`: **el último precio de cada local**,
  del más barato al más caro, con ubicación del local, antigüedad en días,
  `frescura` (`verde` / `amarillo` / `rojo`) y `vencido`. El backend lo calcula con
  los umbrales de `config` (`umbral_verde_dias`, `umbral_amarillo_dias`,
  `ventana_frescura_dias`): es lógica de negocio. El historial completo sigue en
  `/precios`.
- **Ficha:** arriba el mapa con un **cartel de precio por local**, coloreado por
  frescura; debajo la lista («Más barato», local, estado de frescura y fecha
  siempre visible). **Tocar un precio de la lista lo resalta en el mapa** y lo
  centra; **tocar un cartel del mapa resalta su fila** y lleva la lista hasta ahí.
- **Mapa:** `flutter_map` con teselas de OpenStreetMap, sin clave de API ni cuenta.
  Las teselas públicas de OSM **no son para uso masivo** (política de uso): sirven
  para el grupo cerrado; antes de abrir la app hay que pasar a un proveedor de
  teselas (varios tienen plan gratis) o servirlas uno mismo. Cambiar el proveedor
  es cambiar la URL de la capa. **Es una decisión abierta con fecha límite: antes
  de repartir la app fuera del grupo cerrado** (ver «Decisiones»). Google Maps:
  descartado por ahora (clave y cuenta de facturación); **se reevalúa tras usar la
  app con el grupo cerrado**.
- **Ajustes tras la prueba en el celular:**
  - **Globo con punta:** el cartel de precio es más chico y termina en una punta
    (▼) que señala el local; el globo queda por encima de la posición exacta.
  - **Solo precios cerca:** con la ubicación del usuario, el backend filtra por
    `config.radio_precios_m` (5000 m por defecto) y devuelve `distancia_m`. Sin
    precios en el radio, la ficha lo dice y ofrece «Ver precios en otros lugares»
    (sin filtro). Sin ubicación (permiso o GPS apagado), se muestran todos.
  - **Lista corta:** 5 precios y «Mostrar más (N)» / «Mostrar menos». Tocar un
    cartel del mapa despliega la lista si ese local estaba oculto.
  - **Orden:** chips Precio (por defecto) · Cercanía · Frescura. «Más barato» se
    marca siempre en el más barato, sin importar el orden elegido.

### Pendientes cosméticos y de pulido (TODO)

- **Globos de precio en el mapa:** pulir el diseño (tamaño, tipografía, solapado entre
  globos cercanos). Es una mejora cosmética; la versión actual quedó aprobada en la prueba
  en el celular.
- **Precisión del GPS:** a veces es inexacta; alcanza por ahora (el geofence rechaza con
  `precision_baja` cuando pasa `geofence_precision_max_m`).

### Orden por reputación y locales patrocinados (propuesta, no implementado)

**Reputación del local** (para un orden «Reputación»): derivada, no editable.
Combinar (a) cantidad de precios cargados en los últimos N días, (b) cuánto
coinciden con los demás (cuando exista la validación colaborativa), (c) `verificado`.
Se calcula en el backend (negocio) y se expone como `reputacion` (0 a 1); hasta que
exista (b), sería solo (a) y (c), así que conviene no mostrar la palabra
«reputación» todavía.

**Patrocinio** (un local paga para que su producto aparezca arriba):
- *Modelo:* tabla `patrocinios(id, local_id, producto_canonico_id | null, desde,
  hasta, activo, creado_por, nota)`; en Postgres, con `check (hasta > desde)`.
  `producto_canonico_id` nulo = todo el local. Integridad en la base; la regla de
  «cuántos y dónde» en el backend (`config.max_patrocinados` = 1 por lista).
- *API:* `GET .../precios/vigentes` agrega `patrocinado: bool`. Un patrocinado
  aparece **primero y siempre marcado «Patrocinado»**, separado del ranking, y sin
  cambiar su precio ni su frescura reales. Solo entran locales dentro del radio.
  Permiso nuevo `patrocinio.gestionar` (solo admin).
- *Honestidad:* el mapa y el «Más barato» **nunca** se alteran por patrocinio.
  Fijarlo en el Doc 1 antes de implementarlo (cambia lo que promete el producto).
- *UI del admin* (una pantalla de la app, solo rol admin): lista de patrocinios
  con estado (activo / vencido), «Nuevo patrocinio» (elegir local con buscador,
  producto opcional por EAN, fechas desde/hasta) y botón «Pausar». Sin cobro en la
  app: el acuerdo comercial se hace afuera y el admin lo carga.
- *Antes de implementar:* revisar el marco legal de publicidad etiquetada y decidir
  si hay un tope de patrocinados por zona.

- Sin estimación por IPC en esta versión (Doc 1 la prevé, marcada como
  estimación; más adelante).
- Pendiente para después: ordenar o filtrar por distancia al usuario, y mostrar la
  posición del usuario en el mapa (hay que pedir ubicación en la ficha).

## 6. Anti-spam sobre `/v1/auth/anonymous` (corte 9)

El riesgo: el endpoint es público por diseño (la sesión anónima es el onboarding
sin fricción) y cada usuario nuevo puede cargar precios y ganar karma. Capas, de
la más barata a la más pesada:

1. **Aplicar `modo_acceso`** (ya existe en `config`, hoy en `solo_invitacion`,
   pero nada lo lee). Con ese modo, crear una sesión anónima exige un **código de
   invitación**. Es la defensa más fuerte para un grupo cerrado de ~50 personas
   y está en el Doc 1. **Decisión: un código compartido** para el grupo. Va en una
   tabla `invitaciones` (código, usos máximos opcional, usos, vencimiento): hoy
   con una sola fila, y si más adelante se quieren códigos por persona (revocables
   uno a uno) no hace falta cambiar el diseño. La app pide el código solo en el
   primer arranque. Contra: si el código se filtra, hay que rotarlo para todos.
2. **Rate limit por IP** en `/v1/auth/anonymous` y `/v1/auth/refresh` (por
   ejemplo unas pocas altas por hora por IP). Detrás de un proxy hay que leer la
   IP real del header correcto, no la del proxy. Además, el auth de Supabase trae
   su propio límite de altas anónimas por IP en `config.toml` (verificar el valor
   al configurarlo).
3. **Límites por usuario:** tope de cargas de precio y de locales nuevos por hora
   o día (valores en `config`).
4. **Sin karma por duplicados:** repetir el mismo precio del mismo producto en el
   mismo local dentro de la ventana no suma karma. Corta el «farmeo» de karma.
5. **Cuando haya HTTPS público:** Play Integrity (frena emuladores y apps
   modificadas) y, si se compra dominio, poner Cloudflare delante (rate limiting y
   WAF gratis). Esto **no entra en v0.0.2**: no tiene sentido sin deploy.

Lo que sí entra en v0.0.2: 1 a 4. Lo de 5 va con el primer deploy público.

Mientras el backend corra en local y no se comparta, el riesgo real es cero; el
corte 9 existe para que el deploy no nazca vulnerable.

### Lo implementado en el corte 9

- **`modo_acceso`** (`config`, default en código `solo_invitacion`):
  - `abierto`: `/auth/anonymous` crea el usuario sin más.
  - `solo_invitacion`: exige `{"codigo_invitacion": "..."}` en el body. Sin código,
    403 `invitacion_requerida`; código inexistente, vencido o agotado, 403
    `invitacion_invalida` (no se distingue el motivo, para no ayudar a adivinar).
  - `alta_manual` (o cualquier valor desconocido): 403 `alta_cerrada`, no se crean
    usuarios por la API.
- **Invitaciones:** tabla `invitaciones` (`codigo` normalizado en minúsculas y sin
  espacios por un `check`, `usos_max` opcional, `usos`, `vence` opcional). El uso se
  gasta con un único `UPDATE` condicional (no pasa del tope aunque lleguen pedidos a
  la vez; el `check usos <= usos_max` lo garantiza la base). Si el proveedor de auth
  falla después de gastarlo, se devuelve el uso. Dos clases de código conviven:
  el **compartido** (sin tope de usos; `make invitacion CODIGO=grupo [USOS=50]
  [DIAS=30]`; el seed de desarrollo trae `almacenero-dev`) y los **PINs** de abajo.

### PINs de un solo uso, desde el panel

Un PIN es una invitación con `usos_max = 1`; la descripción va en `nota`.

- **Estado calculado, no guardado:** `usada` si `usos >= usos_max`, `vencida` si sin
  usar y `vence` pasó, `disponible` el resto. Guardar además un booleano permitiría
  que se contradigan.
- **Quién y cuándo:** al usarse se anota `usada_at` y `usada_por_auth` (el `sub` del
  token que devuelve el proveedor); el panel lo cruza con `usuarios.auth_id` y muestra
  el alias con link a su ficha. Si el alta falla después de gastar el PIN, se devuelve
  (y se borra ese registro). Un `check` impide fecha o usuario sin uso.
- **Panel → Invitaciones** (`/v1/admin/invitaciones`, capacidades `invitacion.ver` y
  `invitacion.emitir`): generar N PINs (1 a 100) con una descripción y una vigencia
  arbitraria en horas o días (o «no vence»); listar con filtro por estado y búsqueda;
  anular uno **disponible**. Uno usado no se borra (queda de registro: 409). Cada
  alta y baja deja una fila de auditoría por PIN.
- **Generación:** 6 dígitos con `secrets` (no `random`). Si el PIN ya existió (usado o
  no) se sortea otro: lo decide el `UNIQUE`, no una lectura previa.
- **Seguridad de 6 dígitos:** son 10^6 combinaciones, pero cada intento cuenta en el
  rate limit por IP (10 por hora en producción) y hay pocos PINs vivos a la vez; cada
  PIN además vence. No es un secreto de larga vida.
- **Decisión pendiente:** hoy el panel muestra los PINs siempre (el admin los tiene
  que poder pasar). Si algún día importara que no se puedan leer después, se
  guardaría un hash y se mostraría solo al crearlos.

- **Rate limit por IP** (ventana deslizante de 1 hora, **en memoria del proceso**,
  `services/ratelimit.py`): `/auth/anonymous` `auth_altas_por_hora_ip` (10) y
  `/auth/refresh` `auth_refresh_por_hora_ip` (120). En `anonymous` cuentan **todos**
  los intentos, también los de código malo (frena el adivinar códigos). 429 con
  `Retry-After` y `detail.codigo = demasiados_intentos`. Con varias instancias cada
  una cuenta aparte; si el deploy escala, se mueve el contador a Postgres/Redis o a
  Cloudflare sin cambiar la interfaz. La IP: la del socket, o con `PROXY_HOPS=N` la
  N-ésima desde la derecha de `X-Forwarded-For`. El límite de altas anónimas del
  propio Supabase auth no se tocó (el nuestro es más estricto y va primero).
- **Límites por usuario:** `max_precios_por_hora` (60) y `max_precios_por_dia`
  (300), 429 con `detail.codigo = limite_cargas`; las cargas de un mismo usuario se
  serializan con un `select … for update` del usuario para que no se cuelen por
  concurrencia. Los locales nuevos ya tenían `max_locales_por_dia` (corte 5): no se
  agregó límite por hora.
- **Karma por duplicados:** el mismo usuario, producto, local y precio dentro de
  `ventana_frescura_dias` guarda el precio (confirma que sigue vigente) pero **no suma
  karma**. La respuesta de `POST /v1/precios` trae `karma_sumado` (0 o lo que sume la
  carga). Otro usuario que carga el mismo precio sí suma.
- **Decisiones donde el plan era ambiguo:** un solo código compartido, sin código por
  persona (la tabla ya lo permite); el contador de rate limit en memoria; `modo_acceso`
  desconocido = cerrado.
- **App:** si el backend pide código, se muestra una pantalla propia
  (`invitacion_screen.dart`) que **reemplaza** al home: es la única opción, sin
  botón de escanear ni nada más. El código se guarda en el almacenamiento seguro y
  se manda en el alta (solo el primer arranque). Si lo rechaza (inválido, vencido o
  ya usado) se borra y se vuelve a pedir con un aviso. El campo acepta texto (no solo
  números) porque el código compartido de grupo puede tener letras. Un 429 al cargar
  un precio o al crear el usuario se explica en pantalla. Quien ya tenía una sesión
  guardada NO ve esta pantalla (no necesita código): ver docs/03.

## 7. Release firmado y deploy con HTTPS (corte 10: preparación)

### Firmar un build release de Android

1. Generar una **keystore** una sola vez (`keytool`, lo corrés vos: la contraseña
   es tuya y no se comparte).
2. Un archivo `key.properties` local, **ignorado por git**, con la ruta y las
   claves; el `build.gradle.kts` lo lee para el `signingConfig` de release.
3. `flutter build apk --release --dart-define=API_URL=https://...`.
4. **Guardar la keystore en un lugar seguro (y con copia).** Si se pierde, no se
   puede publicar una actualización de la misma app.
5. El build release no lleva el permiso de HTTP sin cifrar (eso está solo en el
   manifest de debug), por lo que **exige HTTPS**.
6. Distribución a ~50 amigos: el APK directo alcanza (hay que permitir
   «instalar apps desconocidas» y las actualizaciones deben ir firmadas con la
   misma clave). Play Store no hace falta ahora (cuenta de desarrollador de pago
   único y requisitos de prueba cerrada; evaluarlo si el grupo crece).
7. El `applicationId` actual (`ar.almacenero.almacenero`) es definitivo una vez
   publicado: confirmalo antes del primer release.

### Backend desplegado con HTTPS

**Supabase solo no alcanza**: Supabase hosted da Postgres, Auth y Storage, pero
el backend FastAPI es una imagen Docker y necesita un host de contenedores.

| Pieza | Dónde | Notas |
|-------|-------|-------|
| Postgres + PostGIS, Auth | Proyecto de Supabase (plan gratis para empezar) | Región Sudamérica (São Paulo). El plan gratis pausa proyectos inactivos y tiene límites de tamaño; revisar condiciones vigentes. |
| Backend FastAPI | Fly.io, Render o Railway (hay que elegir; ver «Elegir host» abajo) | Los tres dan HTTPS automático en su subdominio, **sin comprar dominio**. |
| App | APK firmado | Se instala a mano. |

Variables del backend en producción (secrets de la plataforma, nunca en git):
`DATABASE_URL` (cadena de Supabase; ojo: la conexión directa suele ser solo IPv6
y el *pooler* en modo transacción rompe las *prepared statements* de `asyncpg`,
así que conviene el *session pooler* o ajustar el cliente: probarlo antes),
`AUTH_URL` (`https://<proyecto>.supabase.co/auth/v1`), `AUTH_API_KEY` (la clave
anon), `JWKS_URL`. Las migraciones se aplican a mano a la base remota; **no** se
corre el seed de desarrollo, solo la config inicial y los datos reales.

#### Elegir host: «escala a cero» y arranque en frío

Requisito del dueño: lo más barato posible; no importa que el servicio se duerma
si despierta solo con una petición. Lo que hay que mirar (y **verificar en las
páginas de precios al momento de decidir**, porque cambian):

- **Fly.io:** modelo de pago por segundo y máquinas que se apagan solas
  (`auto_stop_machines`) y arrancan con la primera petición, en pocos segundos. Se
  maneja con la terminal (`flyctl`). Pide tarjeta. Apagada, cuesta solo el disco de
  la imagen. Cuidado: no asumir que «las facturas chicas se perdonan»; confirmarlo
  en la página de precios.
- **Render (plan gratis):** gratis y sin tarjeta, pero el servicio se duerme tras
  unos 15 minutos y el arranque en frío tarda **30 a 60 segundos**. Su Postgres
  gratis caduca: no sirve para este proyecto (la base va en Supabase).
- **Efecto en la app:** hoy la app corta cada pedido a los 15 segundos. Con un
  arranque en frío de medio minuto (Render) habría que **subir el tiempo de espera
  y reintentar**, o mostrar «despertando el servidor…». Con Fly alcanza con un
  reintento. Es un cambio chico en `ApiClient`, y conviene hacerlo antes del primer
  reparto del APK.
- **Base de datos:** Supabase (plan gratis). Ojo: el plan gratis **pausa** los
  proyectos sin actividad durante una semana; un uso mínimo semanal lo evita.
- **Recomendación provisoria:** Fly.io por el arranque rápido y el costo mínimo, si
  no te molesta darle una tarjeta; Render si querés evitar la tarjeta y aceptás el
  arranque lento. La decisión final sigue siendo tuya.

### Dónde van las imágenes

- **Fotos del catálogo (productos canónicos):** son **URLs de Open Food Facts**,
  no se guardan (Doc 2). La app las muestra desde ahí. Más adelante se podría poner
  una caché delante (Cloudflare) si OFF fuera lento o inestable.
- **Fotos subidas por usuarios** (producto nuevo, genérico, foto de góndola):
  **Supabase Storage** (compatible con S3). Están diferidas: no hay subida de fotos
  en v0.0.2. Si el almacenamiento gratis se quedara corto, el siguiente paso es un
  bucket S3-compatible aparte (p. ej. Cloudflare R2, que no cobra la salida de
  datos; verificar condiciones), sin cambiar el código porque la API es S3.

### Dominio: uno solo alcanza para todos tus proyectos

Se compra **un dominio** y los subdominios son **gratis e ilimitados**: son
registros DNS que creás en el panel, sin comprar nada. Cada uno puede apuntar a un
servicio y un proveedor distintos.

```
api-almacenero.ejemplo.com   → backend de este proyecto (Fly/Render/...)
proyecto2-api.ejemplo.com    → backend de otro proyecto, en otro host
blog.ejemplo.com             → un blog
cv.ejemplo.com               → tu CV
```

- **HTTPS por subdominio:** cada host emite el certificado de su subdominio solo
  (Let's Encrypt). No pagás certificados.
- **Un solo nivel de subdominio** (`proyecto1-api.ejemplo.com`, como proponés).
  Evitá `api.proyecto1.ejemplo.com`: los certificados comodín y el proxy gratis de
  Cloudflare cubren un solo nivel.
- **Registrador y DNS:** recomiendo Cloudflare (registro al costo, sin sobreprecio,
  DNS gratis, y delante del backend da rate limiting y WAF: capa anti-spam
  extra). Alternativas: Namecheap, Porkbun. Lo importante es poder editar el DNS
  libremente.
- **Al comprar:** activar la renovación automática y el 2FA en el registrador
  (perder el dominio o que te lo roben es peor que cualquier bug), y dejar activa
  la privacidad del WHOIS.
- **Si usás el proxy de Cloudflare**, el backend debe leer la IP real del cliente
  del header que corresponde (para el rate limit de §6).
- **Un caso aparte** son los `.com.ar`: se gestionan en NIC Argentina y piden
  CUIT/CUIL (verificar requisitos).

La URL de la API queda grabada en el APK, así que con dominio propio se puede
cambiar de host **sin recompilar ni reinstalar nada**.

### `applicationId`

El estándar (heredado de los nombres de paquete de Java) es el **dominio
invertido de algo que controlás** más el nombre de la app: `com.ejemplo.almacenero`.
Así se evitan colisiones entre apps de distintos autores. Reglas: segmentos
separados por punto, al menos dos, cada uno empieza con letra y usa letras,
números o guion bajo.

El actual, `ar.almacenero.almacenero`, **no sigue el estándar del todo**: usé `ar`
como si fuera el TLD y el nombre del proyecto como si fuera un dominio, que no es
tuyo. Funciona, pero no es el criterio recomendado.

**Recomendación:** decidir el `applicationId` **después de comprar el dominio** y
**antes del primer release firmado** (`com.<tu-dominio>.almacenero`). Cambiarlo
ahora es barato: hay que renombrar el paquete en `build.gradle.kts` y mover
`MainActivity`. Efecto secundario: Android lo trata como otra app, así que se
pierde la sesión guardada en los celulares de prueba (el usuario anónimo se
recrea y el karma de prueba queda con el usuario viejo). Una vez publicado, **no
se puede cambiar**.

### Qué tendrías que hacer vos

- Crear la cuenta y el proyecto de Supabase.
- Crear la cuenta en el host elegido (puede requerir tarjeta).
- (Opcional) Comprar el dominio.
- Generar la keystore con tu propia contraseña.

Yo preparo el resto (Dockerfile listo para prod, guía paso a paso en `docs/`,
`make` targets, configuración del `build.gradle.kts`) sin tocar tus cuentas ni
credenciales.

## 8. Panel web de admin (corte 11, en paralelo)

**Para qué:** ver y corregir todo desde una pantalla grande, con acciones masivas. Se
sirve como un servicio más del `docker-compose` (nginx con HTML + JS, sin build pesado)
y habla **solo con el backend** (`/v1/admin/...`), como todo lo demás. No toca la app.
El gestor de base de datos no hace falta: `make up` ya levanta Supabase Studio
(http://127.0.0.1:54323).

**Se pule sobre la marcha:** las necesidades del front y las de datos (migraciones) se
ajustan a medida que se usa.

### Requisitos anotados (para no perderlos)

- **Login de admin desde la web.** Hoy la auth es anónima y un admin es un anónimo
  promovido con `make admin`. La web necesita login real: propuesta, email/contraseña de
  GoTrue, con el rol en `usuarios.rol`. Es prerrequisito del panel.
- **Listado de usuarios**, de dos tipos: **anónimos** y **registrados**. Un usuario
  registrado queda asociado al id anónimo con el que empezó (Doc 1, «Identidad»); en esta
  versión hay un solo anónimo por usuario. El panel debe mostrar esa asociación, alias,
  rol, karma, cantidad de cargas y fecha de alta.
- **Locales:** ver todos, filtrar (`verificado = false`, fuente: OSM/SEPA/usuario/admin),
  **validar** los que vienen del ETL, corregir nombre/dirección/ubicación, fusionar
  duplicados, y acciones masivas.
- **Precios:** listar, filtrar por local/producto/usuario, corregir o borrar (con rastro).
- **Productos y conflictos del ETL** (`make conflictos`): resolverlos desde el panel;
  los campos que resuelve el admin quedan bloqueados contra el ETL (ya existe el trigger).
- **Configuración:** editar `config` (geofence, radios, frescura, `alta_locales_abierta`,
  etc.).
- **Patrocinios** (§5): lista, alta y pausa.
- **Atribuciones** de datos (ODbL, CC BY): texto en `docs/05-fuentes-catalogo.md`; la
  pantalla de la app es otro corte.
- **Auditoría:** toda corrección del admin deja registro (quién, qué, cuándo).
- **Seguridad:** solo rol `admin`; CORS y HTTPS al desplegar; el panel no se publica
  junto con la app sin proteger.

### Implementado (corte 11)

**Cómo se levanta:** `make up` ya construye y levanta el panel (servicio `admin-web` del
`docker-compose`, nginx + HTML/JS con Alpine por CDN, sin build) en http://localhost:8080;
`make admin-web` lo reconstruye solo. Se crea el admin con
`make admin-crear EMAIL=vos@mail.com` (pide la contraseña, o `PASSWORD=...`).

**Decisión de login (prerrequisito).** Email y contraseña de GoTrue, **vía el backend**:
`POST /v1/admin/login` pide la sesión a GoTrue (`/token?grant_type=password`) y solo la
entrega si `usuarios.rol = 'admin'` (si no, 403 y no sale ningún token). El panel renueva
con el `/v1/auth/refresh` de siempre y cada `/v1/admin/*` exige la capacidad
`admin.acceder` además de la propia de cada acción (`permisos.py`). Por qué así y no otra
cosa:
- *No* se «mejora» el login anónimo: un anónimo no tiene credenciales, no se puede
  reingresar desde una pantalla grande. El admin necesita una cuenta de verdad.
- *No* se agrega un rol por API: el rol sigue protegido por trigger. `make admin-crear`
  registra el email en GoTrue (o verifica la contraseña si ya existe) y habilita
  `rol = 'admin'` dentro de su propia transacción, igual que `make admin ALIAS=...`
  (ese sigue sirviendo para la app, pero un anónimo promovido **no** puede entrar al panel).
- El rol vive en Postgres, no en un claim del JWT: revocar un admin es un `update` y vale
  en el siguiente request.
- Sin rate limit propio en el login: lo cubre el de GoTrue y el corte 9 (anti-spam).

**Usuarios anónimos y registrados.** `usuarios` suma `email`, `es_anonimo` y
`anonimo_auth_id`; `app/auth.py` los sincroniza desde los claims del JWT (`email`,
`is_anonymous`) en cada request. Con GoTrue, ligar un anónimo a un email conserva su id,
así que `anonimo_auth_id` (el id anónimo con el que empezó) coincide con `auth_id`; queda
null para quien nació registrado (el admin). El panel muestra la asociación, alias, rol,
karma, cargas, locales creados y alta. Desde el panel solo se edita el **alias**: rol y
karma siguen protegidos en la base.

**API `/v1/admin`** (capacidad entre paréntesis; todo con tests contra Postgres real):

| Recurso | Qué hay |
|---------|---------|
| `usuarios` (`usuario.ver/editar`) | listar con filtros (tipo, rol, texto) y orden; editar alias |
| `locales` (`local.*`) | listar (verificado, fuente, texto, sin precios); corregir nombre/dirección/ubicación/verificado; **validar en masa**; **fusionar** duplicados (mueve precios, ítems y vínculos ETL); **borrar en masa** (omite los que tienen precios) |
| `precios` (`precio.*`) | listar por local/EAN/usuario/fechas; corregir el monto (no la fecha: la frescura es la de la carga); borrar uno o en masa |
| `config` (`config.editar`) | ver todo (con el default del código) y cambiar el valor global; valida clave conocida, mismo tipo y no negativo |
| `productos`, `conflictos` (`catalogo.*`) | listar/corregir productos (lo corregido queda **bloqueado** contra el ETL) y resolver conflictos A/B, como `make conflictos` |
| `auditoria` (`auditoria.ver`) | listado filtrable |

**Auditoría.** Tabla `auditoria_admin` (quién, qué, cuándo, antes, después, nota),
**solo-agregar por trigger** (ni el backend la modifica ni la borra). Cada corrección la
escribe en la misma transacción. Al borrar un precio, el rastro guarda la fila entera
(es la única copia); el karma que ganó el autor **no** se revierte.

**CORS.** `CORS_ORIGINS` (por defecto `http://localhost:8080,http://127.0.0.1:8080`). El
panel toma la URL del backend de `config.js` (mismo host, puerto 8000). Para abrirlo desde
otra máquina de la red, agregar ese origen en `.env`. Con HTTPS, poner el origen real.

**Fichas por entidad (segunda iteración, tras probarlo).** La tabla cruda se queda (sirve
para cambios y acciones masivas); cada fila tiene un botón **Ficha** que abre un panel
lateral con *todo* lo que se puede hacer con esa entidad, pasando por la lógica de negocio
del backend en vez de tocar celdas sueltas. Las fichas se enlazan entre sí (de un precio a
su local o a su autor, de un local a sus duplicados). Entidades y qué junta cada una:

| Ficha | Contexto que muestra (`GET /admin/<recurso>/{id}`) | Acciones de negocio |
|-------|------|------|
| Local | datos, estado, fuente, quién lo creó, vínculos crudos del ETL, **posibles duplicados** (hasta el doble del radio del alta y similitud ≥ 0,3), precios recientes, cambios anteriores | guardar datos (nombre/dirección/ubicación) con **chequeo de duplicado**; validar / quitar verificación; **fusionar este en aquel** o **absorber aquel**; borrar (solo sin precios) |
| Precio | producto, local (y si está verificado), autor con su karma, validaciones, **comparación con los otros precios del mismo producto en el local** (promedio y % de diferencia, rojo desde ±30 %) | corregir monto con motivo; borrar con motivo y opción de **revertir el karma** que ganó el autor |
| Usuario | identidad (anónimo/registrado, email, asociación al id anónimo), alta, karma, cargas, cargas recientes, locales que creó, cambios anteriores | alias; **cambiar rol**; **ajustar karma** (motivo obligatorio) |
| Producto | datos, origen, uso (precios y locales), campos bloqueados, conflictos, **qué dijo cada fuente** (crudo), cambios anteriores | corregir (bloquea el campo contra el ETL); **desbloquear** un campo; resolver conflictos A/B |

Reglas de negocio nuevas (todas en el backend, auditadas, con tests contra Postgres):
- **Corregir un local no puede crear un duplicado casi seguro.** Mismo criterio que el alta
  (`local_duplicado_metros` y `local_duplicado_similitud`): si el nombre/ubicación nuevos
  coinciden con otro local, responde 409 `local_duplicado` y la ficha pregunta; con
  `forzar: true` el admin confirma que es otro. `forzar` no es una columna ni va a la
  auditoría.
- **Cambiar rol desde la API, solo del panel** (`POST /v1/admin/usuarios/{id}/rol`,
  capacidad `usuario.cambiar_rol`). Esto **ajusta §1**: «el rol no se cambia por la API»
  sigue valiendo para la API pública y la app; el panel es la excepción, porque pasa por
  la capacidad, queda auditado y el trigger sigue exigiendo habilitar la escritura dentro
  de la transacción. Salvaguardas: **no se puede cambiar el rol propio** (nadie se escala
  ni se deja afuera) y **un admin tiene que estar registrado** (un anónimo no puede
  iniciar sesión en el panel). `make admin ALIAS=...` sigue existiendo para el arranque.
- **Ajustar karma a mano** (`usuario.ajustar_karma`): motivo obligatorio, entre -1000 y
  1000, sin cero. Premio o sanción; el trigger de karma se habilita solo en la transacción.
- **Borrar precio con `revertir_karma`**: resta `karma_por_carga` al autor (nunca por debajo
  de 0) y lo anota. Sin la opción el karma queda (como antes). El `motivo` va a la nota
  de la auditoría en correcciones y borrados (también en masa).
- **Desbloquear campos** del catálogo (`catalogo.editar`): solo los que estaban bloqueados;
  devuelve el control al ETL.

Qué quedó para la tabla (masivo, sin ficha): validar y borrar locales, fusionar varios en
uno, borrar precios, edición rápida de celdas. Se priorizaron local, precio, usuario y
producto; config y conflictos ya eran un formulario por fila y siguen igual.

**Sección Catálogo.** Todo lo que cambia productos se agrupó en una sola entrada del menú,
**Catálogo**, con dos solapas: *Productos* (tabla + ficha) y *Conflictos del ETL* (con el
globito de pendientes, también visible en el menú). Es solo reorganización del front: la API
no cambió.

**Siguiente (después de mergear el corte 9 / PR #14, no antes).** El corte 9 trae la tabla
`invitaciones` y el rate limit; construir encima de una rama sin mergear obligaría a
resolver conflictos de migraciones, `permisos.py` y docs dos veces, así que se hace en un
PR aparte cuando esté en `main`. Alcance previsto:
- **Sección «Acceso»** (invitaciones): lista (código, usos/máximo, vencimiento, estado),
  **generar código** (aleatorio y legible, con usos máximos y vencimiento opcionales),
  copiar, pausar/revocar, y el interruptor de `modo_acceso`. Capacidad nueva
  `invitacion.gestionar`; todo auditado.
- **Sección «Actividad sospechosa»**: bandeja para **identificar y catalogar peticiones
  spam** (cola de lo que el rate limit cortó, usuarios con muchas altas/cargas en poco
  tiempo, mismas cargas repetidas), con etiquetas (spam / legítimo / en observación) y
  acciones: bloquear usuario, borrar sus cargas en masa revirtiendo karma (ya existe en las
  fichas) y bajar sus límites. Para poder catalogar hace falta que el corte 9 **registre** los
  eventos (hoy solo corta): se define con él qué se guarda (IP, usuario, ruta, motivo,
  fecha) y cuánto se retiene.
- **Refuerzo de seguridad** que salga de ahí (p. ej. bloqueo temporal por IP, umbrales
  editables desde Configuración).

**Pendiente del corte** (no entró): patrocinios (§5: falta fijar la regla en el Doc 1
antes de implementarlos), atribuciones y alta de productos nuevos. Sin HTTPS ni
protección extra el panel **no se publica junto con la app** (ver Seguridad).

## 9. Moderación: escalera por karma negativo y baja de cuentas (corte 12)

El Doc 1 dice que el karma se pierde al acumular calificaciones negativas, pero la
validación colaborativa (la que penalizaría sola) está fuera de alcance. En este corte
el karma negativo lo pone **el admin a mano** (`usuario.ajustar_karma`, ya existía) y la
escalera queda lista para que una penalización automática futura la use sin cambios.

### Decisiones (tomadas antes de codear)

1. **El escalón se deduce, no se guarda.** Se calcula del karma y de dos umbrales en
   `config`:

   | Escalón | Condición (karma ≤ umbral) | Qué pasa |
   |---------|----------------------------|----------|
   | `normal` | karma > `karma_umbral_aviso` | nada |
   | `aviso` | karma ≤ `karma_umbral_aviso` (default **-5**) | la app avisa; sigue usando todo |
   | `restringido` | karma ≤ `karma_umbral_restriccion` (default **-15**) | no puede **cargar** (precios, locales); sí **consultar** |

   Guardar el escalón además del karma permitiría que se contradigan (karma -20 y
   «normal»). Deducido, subir el karma —por ajuste del admin o por una carga futura—
   levanta la restricción solo. Los dos umbrales se editan en el panel (Config); no se
   admite `restricción > aviso` (la escalera tiene que bajar): se valida al guardar.
   Un **admin nunca se restringe por karma** (no se puede trabar a quien administra);
   su escalón es siempre `normal`.
2. **El estado de la cuenta sí se guarda:** `usuarios.estado` (`activo` | `baja`, con
   `check` en Postgres) y `usuarios.baja_at`. La baja es una decisión humana, no se
   deduce de nada. Se protege con un trigger igual que el rol y el karma
   (`app.estado_write`): ningún endpoint de usuario común puede tocarlo; solo el endpoint
   de admin, dentro de su transacción. El motivo (obligatorio) queda en `auditoria_admin`,
   no en una columna: ahí ya está el historial completo de bajas y reactivaciones.
3. **Un admin no se puede dar de baja** y nadie se da de baja a sí mismo (409): primero
   se le saca el rol de admin (que ya tiene sus propias reglas). Evita dejar el panel sin
   dueño por un click.
4. **La baja se aplica en el backend, no en GoTrue.** Todo acceso pasa por `current_user`
   (cada request mira la fila del usuario en Postgres), así que la baja vale **en el
   siguiente request**, también con un token todavía vigente — igual que revocar un admin
   (§8: el rol vive en Postgres, no en el JWT). La otra mitad del cerco es
   `/v1/auth/refresh`: después de que el proveedor renueva, el backend mira a quién
   pertenece la sesión nueva y, si está de baja, **no la devuelve** (403 `cuenta_baja`).
   *Banear en GoTrue además* exigiría la service key (un secreto nuevo con poder total
   sobre los usuarios) y no agrega cerco: el cliente habla solo con el backend (regla de
   arquitectura), y un token que solo sirve contra un backend que lo rechaza no sirve para
   nada. Si algún día hubiera otro consumidor de GoTrue (por ejemplo, Realtime directo),
   se reevalúa.
5. **Código de error en la app: 403, no 401.** Un 401 hace que la app «vuelva a empezar
   anónima» (crearía otra cuenta). Un 403 con `detail.codigo = cuenta_baja` no se
   reintenta ni se renueva: la app muestra una pantalla final y no vuelve a pedir sesión.
6. **El agujero de la cuenta nueva.** Un usuario de baja puede intentar crearse otra
   cuenta anónima. Con `modo_acceso = solo_invitacion` necesita otro PIN: por eso la
   ficha del usuario muestra **con qué PIN entró** (`invitacion_codigo` y su nota), y
   el listado de invitaciones marca los PINs usados por cuentas de baja. Eso permite
   rastrear al que vuelve y no volver a invitarlo. No hay más defensas en este corte
   (con `modo_acceso = abierto` el agujero queda abierto, y es lo que ya se sabía).
   Con el código **compartido** solo se guarda el último que lo usó: el rastro fino lo dan
   los PINs de un solo uso.
7. **Qué ve la app** (mínimo): en la pantalla principal, con escalón `aviso`, una tarjeta
   no punitiva («Tu karma está bajo… si sigue bajando no vas a poder cargar precios»);
   con `restringido`, otra («Por ahora solo podés consultar»); al intentar cargar
   restringido, el error trae `detail.codigo = cuenta_restringida` (403, como
   `limite_cargas` pero 429) y la pantalla de carga lo explica; con la cuenta de baja,
   una pantalla que reemplaza al home, sin botones de escanear.

### Qué se bloquea con `restringido`

Todo lo que **escribe** información de otros: `POST /v1/precios` y `POST /v1/locales`
(las capacidades `precio.cargar`, `local.proponer`, `local.crear` del módulo
`permisos.py`). Leer catálogo, precios, mapa y locales sigue andando. Hay un solo punto
que lo decide (`permisos.exigir_carga`), así que una validación colaborativa futura
(que también «escribe») lo reutiliza.

### API del panel

- `POST /v1/admin/usuarios/{id}/baja` y `/reactivar` (capacidad `usuario.dar_baja`),
  cuerpo `{"motivo": "..."}` obligatorio (3 a 300 caracteres), auditoría
  `usuario.baja` / `usuario.reactivar`.
- `GET /v1/admin/usuarios` suma `estado` y `escalon` y los filtros `estado` y `escalon`;
  la ficha suma `invitacion_codigo` / `invitacion_nota`.
- El karma se sigue ajustando con `POST /v1/admin/usuarios/{id}/karma` (motivo obligatorio).

### Mensajes de moderación (ajuste del corte 12)

- El karma se escribe siempre igual, sin paréntesis: «Karma: -6» en el inicio, «Tu karma
  está en -6» en el aviso y en la restricción, «Tu karma ahora es -6» al cargar.
- Restringido: el botón «Cargar precio» de la ficha queda apagado y la tarjeta explica el
  motivo (el backend sigue rechazando con 403 por si el escalón cambió a mitad de uso).
  El texto **no promete que el karma suba solo**: hoy solo sube cargando (que está
  pausado) o con validación de otros (que no existe), así que la salida es el admin.
- Baja a mitad de uso: la app consulta `/me` cada 30 s y al volver al primer plano
  (`VigilanteDeCuenta`), porque el backend no puede «empujar» el aviso: sin esa consulta,
  quien está quieto en una pantalla se entera recién al tocar algo. `ApiClient.onCuentaBaja` avisa ante CUALQUIER 403 `cuenta_baja` y
  `AlmaceneroApp` reemplaza toda la app por la pantalla de baja, en el momento.

### Dispositivo (ANDROID_ID, corte 12)

Para frenar a quien se da de baja y vuelve a entrar con otro PIN. La MAC no sirve (desde
Android 10 las apps no pueden leerla); se usa `ANDROID_ID` (por dispositivo y firma de la
app). Decisiones:

- **Qué se guarda:** solo un hash (`sha256`), nunca el ID en claro, en la tabla
  `dispositivos (hash, auth_id, primera_vez, ultima_vez)`. Una fila por par
  dispositivo-cuenta. No hay FK a `usuarios`: en el alta el usuario todavía no existe.
- **Cómo llega:** header `X-Device-Id` en `POST /v1/auth/anonymous`, `/v1/auth/refresh` y
  `GET /v1/me`. `/me` (cada arranque) asocia a las cuentas que ya tenían sesión vigente y
  nunca pasan por el alta ni el refresh; solo reescribe `ultima_vez` si pasó más de 1 h. Un valor ausente o
  inválido (largo fuera de 8–128) se ignora: no rompe la app, solo no deja rastro.
- **Qué hace:** si el dispositivo está asociado a una cuenta **de baja**, el alta de una
  cuenta nueva se rechaza con 403 `cuenta_baja` **antes** de gastar el PIN, y la app
  muestra la pantalla de baja. Al reactivar la cuenta deja de bloquear (decide el estado
  actual). No se bloquea por restricción, solo por baja.
- **Panel:** la ficha muestra «Otras cuentas en el mismo dispositivo» (alias, estado) para
  que el admin vea el vínculo, por ejemplo cuentas nuevas de la misma persona.
- **Límites aceptados:** un borrado de fábrica cambia el ID; un celular vendido o regalado
  no debería heredar una baja y se resuelve con el formulario de rehabilitación (punto 1).
  Un cliente modificado puede mandar otro ID: es una valla, no una garantía.
- **Privacidad:** es un dato de identificación del dispositivo; se guarda hasheado y se
  debe mencionar cuando se redacte la política de privacidad del release.

### Pendiente para un próximo corte (anotado para que no se pierda)

1. **Formulario de rehabilitación** en la pantalla de baja (y de restricción): la persona
   pide revisión con un texto; el admin lo ve en el panel, conversa con ella y decide.
   Reemplaza el «contactá a los administradores» provisorio de la pantalla de baja
   (decir «hablá con quien te invitó» puede no ser cierto si los PINs se reparten o esa
   persona ya no es admin).
2. ~~Identificador de dispositivo~~ → **hecho en el corte 12, ver «Dispositivo» abajo.**
3. **Aviso de rehabilitación**: cuando se levanta una restricción o se reactiva una
   cuenta, mostrar en la app «tu cuenta volvió a estar habilitada» **y por qué** (el motivo
   que cargó el admin). Hoy el aviso simplemente desaparece. Necesita guardar el
   motivo/evento para mostrarlo una vez. A futuro, notificación push.
4. Contacto fijo en la app si se abre al público: **no por ahora**; lo resuelve el
   formulario del punto 1.

## 10. Calidad del catálogo, CSV curado, ETL desde el panel y sugerencias (cortes 13-18)

**Estado: diseño de la fase 1; el dueño ya decidió lo de abajo y falta confirmar el orden de cortes.** Criterios de normalización,
mediciones y los casos reales: `docs/07-normalizacion-catalogo.md`. Mediciones de costos
(2026-11-21, de las páginas de precios; **verificar de nuevo al contratar**): Fly.io
`shared-cpu-1x` 256 MB ≈ US$ 2,19/mes encendida todo el mes, facturada por segundo
([precios](https://fly.io/pricing-update/)); Supabase gratis: base de 500 MB, 5 GB de egreso y
pausa tras una semana sin actividad ([precios](https://supabase.com/pricing)). El catálogo
actual (134 505 productos con crudo) pesa ~75-80 MB: entra bien; OFF completo (2,4 GB) no.

### A. Disparar los ETL desde el panel

**Decisión de diseño: una cola en Postgres y dos tipos de ejecutor.** El panel no corre nada
pesado dentro del backend web (256 MB de RAM, y un proceso largo lo tira o lo deja sin
responder):

- **Tabla `etl_ejecuciones`**: `id`, `etl` (clave), `parametros jsonb`, `estado`
  (`en_cola` · `corriendo` · `ok` · `fallo` · `cancelando` · `cancelada`), `ejecutor`
  (`web` · `local`), `creado_por`, `creado_en`, `iniciado_en`, `terminado_en`, `latido_en`
  (el ejecutor lo renueva cada pocos segundos: sin latido por 2 min → se marca `fallo`),
  `reporte jsonb` (filas leídas, nuevas, actualizadas, descartadas por motivo: el `Reporte`
  que ya existe en `etl/comun/catalogo.py`), `log text` (últimas ~64 KB; las líneas viejas se
  recortan), `cancelar bool`. La toma de trabajos es `for update skip locked`; una sola
  ejecución a la vez por ejecutor. Todo `iniciar`/`cancelar` pasa por `auditoria_admin`.
- **Definición de cada ETL en código** (`etl/registro.py`): `clave`, `titulo`, `descripcion`,
  `ejecutor` (`web` o `local`), y `parametros = [Param(nombre, tipo, obligatorio, ayuda,
  default, opciones)]` con tipos `texto | entero | booleano | opcion | fecha | archivo`. El
  panel pide la lista (`GET /v1/admin/etl`) y **dibuja el formulario a partir de ella**; el
  backend valida el payload contra la misma definición. Los `__main__` actuales quedan como
  envoltorios finos del mismo `ejecutar(parametros, ctx)` (`ctx.log()`, `ctx.cancelado()`,
  `ctx.reporte`), así que **corre lo mismo que corre hoy**.
- **Ejecutor `web`** (livianos: importar un CSV curado, re-normalizar, recalcular calidad):
  el backend lanza **un subproceso** (`python -m etl.ejecutar <id>`), no un hilo, con tope de
  memoria y de tiempo, de a uno por vez. La imagen del backend incluye `etl/` **sin** los
  extras pesados (`pyosmium`). Costo adicional: 0 (la máquina ya existe).
- **Ejecutor `local`** (pesados: bajar y leer SEPA/OFF/OSM): `make etl-worker` en tu
  máquina consulta la cola de la base remota (conexión saliente, **sin abrir puertos**), toma
  lo que esté marcado `local` y lo ejecuta con tus archivos. En el panel el botón es el
  mismo y se ve el mismo estado/log; solo que corre en tu Mac, con tu ancho de banda.
  **Costo: 0**; el tráfico hacia Supabase es de entrada (≈ 80 MB para una carga de SEPA
  completa, medido con el tamaño de las tablas).
- **Opción descartada por ahora:** una máquina Fly aparte por corrida (`fly machine run`).
  Es viable (se paga por segundo mientras corre) pero suma operación y secretos en Fly para
  algo que cabe en tu Mac; no se descarta para más adelante.
- **Archivos que entran por el panel** (el CSV curado): se guardan **temporalmente en la
  base** (`etl_archivos`, bytea, tope 25 MB comprimido) en vez de en disco (el disco de Fly es
  efímero y de ~0 GB útil para esto), porque así lo ven por igual el ejecutor `web` y el
  `local`. Se borran al terminar la importación; queda solo metadato y hash (§B).
- **Cancelación:** `cancelar = true`; el ETL lo mira entre lotes (cada 20 000 filas) y
  corta limpio (cada lote es una transacción). Si no responde en 30 s y corre en el mismo
  host, SIGTERM.
- **Capacidades** (`permisos.py`): `etl.ver`, `etl.ejecutar`, `etl.cancelar`; solo admin.
  Panel: sección **ETL** (lista de definiciones → formulario → historial con estado, filas,
  duración y log).

**Implementado en el corte 18 (así quedó, con lo que se precisó):**

- **Migración** `20261128000001_etl_ejecuciones.sql`: `etl_ejecuciones` (estados `en_cola` · `corriendo` ·
  `cancelando` · `ok` · `fallo` · `cancelada`; un índice único parcial garantiza **una sola ejecución a la
  vez por ejecutor**), `etl_archivos` (bytea, tope 25 MiB por check) y `auditoria_admin` acepta la
  entidad `etl`. `catalogo_lotes.etl_ejecucion_id` ahora es FK.
- **Definiciones** en `etl/registro.py` (`Param`, `Definicion`, `validar`, `describir`) y
  `etl/definiciones.py`: `curado_importar`, `catalogo_renormalizar`, `catalogo_calidad` (ejecutor
  `web`); `off`, `sepa`, `sepa_locales`, `osm`, `curado_exportar` (ejecutor `local`). Cada una llama al
  mismo código que los `make etl-*`. Imports perezosos: pedir la lista no carga `pyosmium`.
- **Un solo supervisor para los dos ejecutores** (`etl/ejecucion.py`): toma con `for update skip locked`,
  corre `python -m etl.ejecutar <id>` como **subproceso** (tope de tiempo; de memoria en Linux), renueva el
  latido cada 2 s, vuelca la salida al log (últimos 64 KB) y marca `fallo` a lo que lleve más de 2 min sin
  latido. El **ejecutor `web`** es una tarea de fondo del backend (`app/services/etl.py`, se apaga con
  `ETL_WEB_ACTIVO=false`); el **ejecutor `local`** es `make etl-worker` (`etl/worker.py`), conexión saliente
  a la base de `DATABASE_URL`, sin abrir puertos.
- **Cancelar** (diferencia con el diseño): en vez de que el ETL mire un flag entre lotes, el supervisor ve
  `cancelar = true` en cada latido y le manda SIGTERM al subproceso (SIGKILL a los 30 s). Es equivalente,
  porque cada lote es una transacción (Postgres deshace el abierto), y no obliga a tocar cada ETL. Una
  ejecución `en_cola` se cancela directo.
- **Archivos:** `POST /v1/admin/etl/archivos?nombre=…` con el archivo como cuerpo crudo (sin
  `python-multipart`). Se guardan en `etl_archivos` y **se borran al importar de verdad** (`aplicar`) o a las
  24 h; un simulacro lo deja para confirmar (`Definicion.consume_archivo_con`). El panel ofrece «Importar de
  verdad» tras un simulacro ok. Queda solo el metadato en `parametros` y el hash en `catalogo_lotes`.
- **API** (`/v1/admin/etl`): `GET /` (definiciones), `POST /archivos`, `DELETE /archivos/{id}`,
  `POST /{clave}/ejecutar`, `GET /ejecuciones` (sin log), `GET /ejecuciones/{id}` (con log),
  `POST /ejecuciones/{id}/cancelar`. Capacidades `etl.ver`, `etl.ejecutar`, `etl.cancelar` (solo admin). Todo
  `etl.iniciar`/`etl.cancelar`/`etl.archivo_*` va a `auditoria_admin` en la misma transacción. Errores con
  regla (§10-E): `etl_parametro_invalido` (dice cuál), `etl_archivo_vacio`, `etl_archivo_grande`,
  `etl_archivo_inexistente`, `etl_ya_terminada`.
- **Panel:** sección **ETL** (formulario generado desde la definición, subida de archivo, historial con
  estado/filas/duración, log y reporte, cancelar; se refresca solo mientras haya algo activo).
- **Imagen del backend:** el contexto de build pasó a la **raíz del repo** (`docker-compose.yml`,
  `backend/Dockerfile`, `.dockerignore`) para incluir `etl/` junto a `app/`. Quien despliegue (corte 10)
  debe construir con ese contexto.

### B. CSV curado en vez de bajar OFF entero cada vez

**Respuesta corta: no, bajar y leer 1,5 GB cada vez no es sensato.** Medido en este
proyecto (Doc 5 §2): 40 min de descarga, 14 min de proceso, 4 916 182 filas leídas para
quedarnos con 61 463 (1,25 %). Para un catálogo argentino, lo correcto es **extraer una vez
los productos relevantes y guardar ese extracto como CSV**.

- **Qué es relevante:** OFF con `countries_tags` de Argentina y vecinos; SEPA con los EAN
  más frecuentes (columna `filas`: cuántas cadenas lo informan); lo que ya tenga precio
  cargado en la app; y lo que el dueño agregue a mano.
- **Formato (`catalogo_curado_v1`)**: CSV UTF-8, separador `,`, con cabecera de comentarios
  `#` (`# formato: catalogo_curado_v1`, `# generado: …`, `# normalizador: <versión>`,
  `# fuentes: sepa:<sha256>, off:<sha256>`) y columnas: `ean, nombre, marca,
  tamano_valor, tamano_unidad, pack_cantidad, presentacion, imagen_url, fuente_origen, nota`.
  Las filas ya están **normalizadas** (§C). Un archivo `.gz` también se acepta.
- **Flujo de subida** (panel: ETL → «Importar CSV curado»): (1) se sube el archivo;
  (2) **validación en seco** (no escribe): EAN válido, unidad permitida, largos, duplicados
  dentro del archivo, y un reporte «X nuevos, Y cambian, Z sin cambios, W inválidos» con
  las primeras filas con error; (3) el admin **confirma**; (4) se importa en lotes con la
  misma fusión idempotente (`fusionar_lote`), con `fuente = 'curado'`; (5) se **borra el
  archivo** y se guarda el lote.
- **Prioridad:** `manual > curado > sepa > off` (el curado es lo que el dueño revisó).
  Requiere ampliar los checks de `fuente`/`origen` y la config de prioridad (migración
  pequeña).
- **Qué se conserva para poder reconstruir** (tabla `catalogo_lotes`, una fila por
  importación): `id`, `formato`, `version_normalizador`, `nombre_archivo`,
  `sha256` del CSV, `filas`, `nuevos/cambiados/iguales/invalidos`, `fuentes_entrada` (nombre
  + sha256 + fecha de cada archivo de origen: el zip de SEPA, el CSV de OFF),
  `subido_por`, `creado_en`, `etl_ejecucion_id`. El CSV **no** se guarda en la base; lo que
  queda es el dato (que ya está en `productos_canonicos` y `producto_fuentes`) y la receta.
- **Reproducibilidad:** `make catalogo-curado` regenera el CSV desde las fuentes crudas
  (`etl/data/…`) con el mismo normalizador versionado, y su salida lleva el hash del
  archivo; si las fuentes y la versión coinciden con las del lote, el `sha256` tiene que
  coincidir (se prueba). Además **no hace falta volver a las fuentes** para re-normalizar:
  `producto_fuentes` guarda el crudo de cada una; `make catalogo-renormalizar` rehace
  `productos_canonicos` desde ahí al cambiar `normalizador_version`.
- **Periodicidad:** el dueño decide; recomendación: OFF cada 3-6 meses (cambia poco para
  Argentina), SEPA mensual (cada corrida solo toca lo que cambió, ya es idempotente).

**Implementado en el corte 17 (así quedó, con lo que se precisó):**

- **Migración** `20261127000001_catalogo_curado.sql`: `curado` es origen/fuente válida
  (`productos_canonicos.origen`, `producto_fuentes.fuente`, `conflictos_catalogo`), `prioridad_fuente()`
  queda `manual > curado > sepa > off` (si la config guardada no nombra `curado`, queda justo
  después de `manual`) y nace `catalogo_lotes`.
- **Código** en `etl/curado/`: `formato.py` (columnas, validación fila a fila, lectura/escritura),
  `exportar.py` y `importar.py`. Comandos: `make catalogo-csv-exportar` y
  `make catalogo-csv-importar ARCHIVO=… [APLICAR=1] [FORZAR=1]` (sin `APLICAR` es un simulacro).
- **Hash del contenido, no del archivo.** El `sha256` se calcula sobre la fila de columnas + los
  datos (ordenados por EAN, `\n`, sin BOM), no sobre el archivo entero: así el `# generado:` de la
  cabecera, el `.gz` o un `\r\n` no lo cambian y el exportador es **reproducible** (dos corridas
  con las mismas fuentes y la misma `NORMALIZADOR_VERSION` dan el mismo hash; medido con SEPA de un
  día + la muestra de OFF: 77 316 filas, mismo hash las dos veces). La cabecera trae también
  `contenido_sha256` (el declarado): si alguien edita el CSV a mano el importador avisa que no
  coincide, lo importa igual y guarda ambos hashes.
- **Exportador sin base de datos:** lee OFF (filtra países como `make etl-off`) y los zips de SEPA
  (`SEPA_MIN_FILAS` descarta EAN con pocas filas), normaliza cada fuente, y por EAN gana SEPA y OFF
  completa lo que falte (`fuente_origen` = `sepa`, `off` o `sepa+off`). Lo que ya está en la base (lo
  manual, lo con precios) **no** se exporta: ya está ahí.
- **Validación en seco = la importación real, revertida.** Cada lote corre `fusionar_lote` con
  `fuente = 'curado'` dentro de una transacción que se deshace (en `APLICAR=1` se confirma). El
  reporte dice: inválidas con motivo y número de línea, repetidas en el archivo (gana la última),
  EAN nuevos, actualizados (con ejemplos «campo: antes → después»), sin cambios y conflictos
  nuevos. «Actualizados» cuenta solo cambios de datos; pasar un producto de `sepa` a `curado`
  sin cambiar nada se informa aparte («pasan a figurar como `curado`»).
- **Respeta lo humano:** lo cargado a mano y los campos bloqueados no se pisan (prioridad +
  trigger existentes); el curado sí pisa a SEPA y OFF.
- **Trazabilidad:** `producto_fuentes` (fuente `curado`) guarda por EAN `fuente_origen`, `nota`,
  `archivo_sha256` y `formato`; `catalogo_lotes` guarda, por importación aplicada, hash,
  versión del normalizador, conteos y el hash de cada archivo crudo de entrada. El CSV **no** se
  guarda. Importar el mismo archivo con la misma versión del normalizador no hace nada (avisa el
  lote anterior); `FORZAR=1` lo corre igual.
- **Receta para reconstruir (y poder borrar el CSV):** volver a correr `make catalogo-csv-exportar`
  con las mismas fuentes (nombre + hash en `fuentes_entrada`) y la misma versión; el `sha256` tiene
  que coincidir con el del lote.

**Ajustes del corte 18 sobre B y el panel (2026-11-24, a pedido del dueño):**

- **Los exports piden solo un nombre de archivo.** Tipo de parámetro `nombre_archivo` del registro de
  ETL (`etl/registro.py`): sin carpetas, sin `..`, termina en `.csv` o `.csv.gz`. La carpeta base la
  decidimos nosotros: `ETL_EXPORT_DIR` (por defecto `etl/data/exports/`, ignorada por git). Vale para
  el formulario del panel, la CLI y el Makefile (`CURADO_SALIDA` ahora es un nombre, no una ruta; ver más abajo: sin extensión).
  Así un formulario no puede escribir en cualquier lado de la máquina del worker.
- **Formato de intercambio v2 (`catalogo_curado_v2`) con los metadatos del tratamiento** y
  **exportación desde la base** (`make catalogo-csv-exportar-base`; panel: ETL → «Exportar el
  catálogo»). Cada fila lleva `origen`, `campos_bloqueados`, `calidad`/`estado`/`motivos`,
  `normalizador_version`, `cargado_a_mano`, `revisado`, y conteos de ediciones del admin,
  sugerencias, avisos del normalizador y conflictos. Son conteos y banderas, **sin ids de
  personas**. El importador lee v1 y v2 y, con un v2, **restaura** origen y campos bloqueados
  (reglas de convergencia en el Doc 9 §5); lo demás queda en `producto_fuentes.datos.intercambio`.
  El formato y sus decisiones están en **`docs/09-formato-intercambio-catalogo.md`** porque se va a
  reutilizar en otro proyecto. Verificado con el catálogo local completo: 134 506 filas exportadas,
  simulacro de reimportación = 0 inválidas, 0 cambios, 0 cambios de origen.
- **Conflictos: «Editar y resolver».** Catálogo → Conflictos (y la ficha del producto) suma, junto a
  «Dejar A» / «Usar B», una tercera acción para cuando ninguna de las dos está bien (unidades mal,
  nombre mal…): abre un formulario con los datos actuales del producto; al guardar se escriben con el
  mismo camino que la corrección directa (`services.catalogo.aplicar`: bloquea lo corregido y
  recalcula la calidad) y el conflicto queda `resuelto` con `elegido = 'manual'`. Reglas:
  tiene que corregir al menos el campo en disputa (si no, 422 y sigue abierto); se cierran también
  los demás conflictos pendientes de ese producto sobre los campos corregidos; se audita
  `conflicto.editar` (con el motivo opcional) y `producto.corregir` (aparece en el historial del
  producto). Migración `20261129000001_conflicto_edicion_manual.sql` (el check de `elegido` admite
  `'manual'`). API: `POST /v1/admin/conflictos/{id}/editar`.

**Segunda tanda de ajustes del corte 18 (2026-11-24, a pedido del dueño):**

- **Los exports no piden extensión.** Solo un nombre (`catalogo-2026-11`); el sistema agrega `.zip`
  (si alguien escribe `.zip`/`.csv`/`.csv.gz`, se ignora). Sin elegir formatos.
- **El export es un `.zip` con el CSV y un `LEEME.txt`** que cuenta qué se hizo: cuántos productos
  tienen cada tratamiento, **qué reglas del normalizador se aplicaron** (a cuántos y con un ejemplo),
  motivos de calidad, columnas y cómo importarlo (`etl/comun/paquete.py`, `etl/curado/leeme.py`). El
  importador reconoce zip/gzip/CSV por el contenido (no por la extensión). El hash de contenido no
  cambia con el contenedor.
- **Las reglas del normalizador se imprimen** también al cargar SEPA y OFF y al importar un curado
  (`Reporte.trazas`, el mismo informe que usa «Renormalizar»), y al armar el curado desde las fuentes.
- **Importar con selector de archivo:** el formulario del panel sube el archivo al servidor antes de
  ejecutar (`<input type="file">`, hasta 25 MB; ya existía `POST /v1/admin/etl/archivos`): ahora
  acepta el `.zip` del export, muestra «Subiendo…» y el nombre/tamaño subido.
- **Locales validados intercambiables** (`locales_intercambio_v1`, Doc 9 §8): ETL «Exportar locales»
  (worker local; por defecto solo `verificado`) e «Importar locales» (con selector de archivo y
  simulacro). Sin tocar al existente, sin personas, conserva `fuente` y vínculos OSM/SEPA. Sin
  migración nueva. CLI: `make locales-exportar` / `make locales-importar`.

### C. Calidad y normalización

Todo en `docs/07-normalizacion-catalogo.md` (reglas, puntaje, casos). Resumen de lo que se
mide hoy (134 505 productos): 61,1 % sin tamaño, de los cuales **~11 pp son recuperables del
nombre**; 12,4 % con marca placeholder; 17 % de variantes de escritura de marca; 10,1 % con
mayúsculas mezcladas; solo 0,2 % tiene un nombre inservible (el único descarte duro).

### D. Rol «moderador» y cola de sugerencias (diseño; **no se implementa en la app sin acordarlo**)

- **Rol:** `usuarios.rol` suma `moderador` (ampliar el check; el trigger de protección del
  rol queda igual). En `permisos.py`: `moderador` = `usuario` + `catalogo.sugerir`; `admin`
  suma `catalogo.sugerencias.resolver`. Los endpoints preguntan por la capacidad, no por el
  rol (la regla de `permisos.py` ya existente). Un moderador **restringido por karma** pierde
  `catalogo.sugerir` (es una capacidad de carga: entra en `CAPACIDADES_DE_CARGA`).
- **Tabla `sugerencias_catalogo`**: `id`, `producto_id` (null = alta de producto nuevo),
  `ean`, `usuario_id`, `cambios jsonb` (solo `nombre`, `marca`, `tamano_valor`,
  `tamano_unidad`, `pack_cantidad`, `presentacion`), `motivo text`, `estado`
  (`pendiente` · `aprobada` · `rechazada` · `reemplazada`), `resuelto_por`, `resuelto_en`,
  `nota_resolucion`, `created_at`. Índice único parcial: una sugerencia **pendiente** por
  (producto, usuario). `check` de coherencia estado/resuelto como en `conflictos_catalogo`.
- **Aprobar** = aplicar los cambios por **el mismo camino que la corrección del admin**
  (`PATCH /admin/productos`: bloquea los campos contra el ETL) y registrar en
  `auditoria_admin`, todo en una transacción. **Rechazar** exige nota. Si el producto cambió
  desde que se sugirió, la sugerencia se muestra con el valor actual al lado.
- **Karma:** aprobada → premio (config `karma_sugerencia_aprobada`); rechazada → sin castigo
  por sí sola; un patrón de rechazos entra por la escalera de moderación del §9, no acá.
- **Panel:** solapa **Sugerencias** dentro de Catálogo, con globito de pendientes (igual que
  Conflictos), diff «actual → sugerido», y aprobar/rechazar en masa. La ficha de producto
  suma «sugerencias de este producto».
- **App:** una acción «Sugerir corrección / Dar de alta» en la ficha y en el «no encontrado»,
  **visible solo para moderadores** (corte 16; el diseño de pantalla se acuerda antes).
- **Alta de producto nuevo:** `producto_id` null y `cambios` con el EAN completo; al aprobarla
  se inserta con `origen = 'manual'` y campos bloqueados.

**Implementado en el corte 15 (así quedó, con lo que se precisó):**

- **Rol y capacidades.** `moderador` = `usuario` + `catalogo.sugerir` (capacidad de carga: un
  moderador restringido por karma la pierde). `admin` suma `catalogo.sugerir`,
  `catalogo.sugerencias.resolver` y `catalogo.crear` (alta directa). El moderador **no entra al
  panel** (`admin.acceder` es del admin): propone desde la app (corte 16). El rol se asigna
  desde la ficha del usuario en el panel (`POST /v1/admin/usuarios/{id}/rol`) y `GET /v1/me`
  lo devuelve (`rol`) para que la app muestre «Sugerir» solo al moderador.
- **Un solo camino de escritura.** `backend/app/services/catalogo.py` (`aplicar`, `crear`) lo usan
  la corrección directa (`PATCH /admin/productos/{id}`), el alta simple (`POST /admin/productos`)
  y la aprobación de una sugerencia: los tres bloquean contra el ETL, recalculan la calidad y
  auditan igual. Campos que viajan: `nombre`, `marca`, `tamano_valor`, `tamano_unidad`,
  `pack_cantidad`, `presentacion`.
- **Bloqueo ampliado.** `campos_bloqueados` suma `presentacion` (el pack va con `tamano`); el
  trigger y `_SQL_EXISTENTES` del ETL lo respetan. En un alta lo que se dejó vacío **no** se
  bloquea (un ETL todavía puede completarlo).
- **Sin descarte para lo humano.** Un producto con `origen = 'manual'` o con algún campo
  bloqueado no se descarta por incompleto (el estado se calcula normal): `revisado` en
  `puntuar` / `calidad.evaluar` (la prueba de paridad lo cubre).
- **Moderador (app, `/v1/catalogo/sugerencias`).** `POST` propone: si el EAN existe (aunque esté
  descartado) es una corrección y solo cuentan los campos que de verdad cambian; si no, un alta
  (hace falta el nombre). Una sugerencia nueva marca `reemplazada` a la pendiente anterior del
  mismo autor para ese EAN. `GET /mias` lista las propias.
- **Admin (`/v1/admin/sugerencias`).** Listado con `actual` junto a `cambios`, `aprobar`,
  `rechazar` (nota obligatoria) y `resolver` en masa (cada una en su transacción; las que fallan
  se informan). Aprobar suma `karma_sugerencia_aprobada` (config, 3 por defecto) al autor;
  rechazar no resta nada. La ficha del producto lista sus sugerencias.
- **Lo que una persona carga fuera del estándar se corrige (Doc 8).** `make catalogo-renormalizar`
  ahora también pasa el normalizador por el **nombre que puso una persona** (manual o
  bloqueado): lo limpia (marca, tamaño y envase afuera, abreviaturas, mayúsculas) y completa
  los campos **vacíos** con lo que traía adentro; nunca pisa un campo ya cargado. A quien
  cargó se le deja un **aviso** (`avisos_catalogo`, `GET /v1/me/avisos`) con el porqué y los
  estándares incumplidos; **no cambia el karma**. Los estándares viven en
  `backend/app/services/estandares.py` (`GET /v1/ayuda/estandares`, panel → Ayuda,
  `docs/08-estandares-de-carga.md`).
- **Panel.** Catálogo → **Sugerencias** (con globito), **Alta / corrección por EAN** (buscar →
  formulario corto, marca con autocompletado, lo que dijo cada fuente al lado) y el rol
  `moderador` en la ficha de usuario.

**App (corte 16, diseño acordado con el dueño):** la ficha muestra el **nombre limpio** arriba y
debajo «marca · tamaño · presentación · pack de N». Solo los moderadores (y admins) ven la acción:
**menú ⋮ de la barra → «Sugerir corrección»**, y en «no encontrado» el botón «Dar de alta este
producto» (un descartado también da «no encontrado»: la sugerencia es una corrección). El
formulario (nombre, marca, tamaño + unidad, pack, presentación, motivo opcional) viene precargado,
manda **solo lo que cambió** y tiene el enlace «Ver estándares de carga» (`GET /v1/ayuda/estandares`).
Un moderador restringido por karma no ve la acción. **Pendiente (decidido dejarlo para después):** la
pantalla de avisos del usuario (`GET /v1/me/avisos` ya existe).

### E. Errores que explican la regla (ajuste del corte 15, ✅)

**Principio:** una operación que falla en el backend le dice a quien la hizo **qué regla se
violó, por qué y cómo se resuelve**. No se esconden reglas de negocio detrás de un «error»
genérico ni de un «Failed to fetch». Origen: aprobar una sugerencia con `pack_cantidad: 1`
reventó con un 500 mudo (`pack_cantidad_check`) y el panel solo mostraba «Failed to fetch».

- **Catálogo de reglas** (`backend/app/services/reglas.py`): cada regla tiene un `codigo`
  estable, un `titulo`, un `mensaje`, un `como_resolver` y el status HTTP. Hoy: `pack_minimo`,
  `tamano_positivo`, `tamano_con_unidad`, `unidad_invalida`, `ean_formato`, `ean_duplicado`,
  `campo_bloqueado`, `sugerencia_pendiente`, `sugerencia_incoherente`, `dato_invalido`,
  `conflicto_de_datos` y `error_interno`. El nombre de cada constraint de la base se mapea a su
  regla (`POR_CONSTRAINT`); lo que no figura cae en `dato_invalido` con el nombre de la
  restricción. **Regla del equipo:** al agregar un constraint o una validación nueva, se agrega
  su regla.
- **Respuesta:** `detail = {codigo, titulo, mensaje, como_resolver, ...}` (+ `restriccion`,
  `campos` o `referencia` según el caso). Manejadores globales en `backend/app/errores.py`:
  `CheckViolation`/`UniqueViolation`/`RaiseError` de Postgres → 422/409 con la regla; datos ya
  guardados que el modelo actual no acepta (`ValidationError` de pydantic) → 422 con los campos;
  cualquier otra excepción → 500 `error_interno` con una **`referencia`** que también está en el
  log (`docker compose logs backend`). El 500 sale **con cabeceras CORS**: antes salía de
  `ServerErrorMiddleware`, por fuera del CORS, y el navegador lo mostraba como «Failed to fetch».
- **Configurable desde el panel:** Configuración → «Mensajes de error» edita el **texto** de cada
  regla (`config.mensajes_reglas`, `GET/PUT /v1/admin/reglas`, capacidad `config.editar`,
  auditado, máx. 400 caracteres, vacío = el original). El código, el status y la regla en sí no
  se tocan: son lo que la app y los tests usan.
- **Panel y app:** el panel muestra `mensaje → como_resolver [codigo · ref]`, y si el backend no
  responde dice que no hay respuesta (caído o sin red) en vez del «Failed to fetch» del
  navegador. La acción en masa de sugerencias informa la regla de cada una que falló. La app
  muestra el `mensaje` del `detail`.
- **No cubre (a propósito):** los valores de negocio configurables (umbrales, límites) siguen en
  su propia sección de Configuración; esto es solo el *texto* de los errores.

### Decisiones del dueño (2026-11-21)

- **Descarte:** sí se descartan los muy incompletos (estado `descartado`: se guardan pero no
  se muestran; criterio y números en Doc 7 §5), **y** hace falta una **interfaz simple para que
  admins y moderadores den de alta o completen productos** (Doc 7 §5.1). Más un **tablero de
  control** en el panel con los dudosos a revisar.
- **Ejecución de ETL:** cola en Postgres + worker `local` para los pesados + subproceso `web`
  para los livianos (§A).
- **Moderador y sugerencias: antes del release** (solo hay un probador hoy: el dueño; lo quiere
  listo). La acción en la app se muestra solo a moderadores.
- **Ficha:** nombre limpio arriba, detalles abajo. `app/` se toca solo para eso y para la
  acción de sugerir/alta.

### Cortes propuestos (cada uno su rama y su PR a `main`; yo no mergeo)

| # | Corte | Qué trae | Tamaño |
|---|-------|----------|--------|
| 13 | **Normalizador + medidor** | `etl/comun/normalizar.py`, diccionarios (arranque a partir de la medición), tests con los casos reales, `make catalogo-calidad` (la tabla de §1 del Doc 7). Sin migración ni cambios en datos. | medio |
| 14 | ✅ **Integración + calidad en la base + tablero** | Migración (columnas del Doc 7 §3 y estado `descartado`), el normalizador dentro de `fusionar_lote`, `make catalogo-renormalizar`, la búsqueda por EAN oculta los `descartado`, `ProductoOut` con campos nuevos (compatibles), panel: columna/filtro/orden por calidad y **tablero de control** (conteo por estado y motivo). | grande |
| 15 | ✅ **Rol moderador + sugerencias + alta simple** | migración (rol, `sugerencias_catalogo`), capacidades, API; panel: solapa Sugerencias y formulario simple de alta/corrección por EAN (Doc 7 §5.1) con aplicación directa del admin. | grande |
| 16 | ✅ **App: ficha normalizada y sugerir** (`app/`) | nombre limpio + marca · tamaño · presentación; acción «Sugerir / dar de alta» solo para moderadores. Se acuerda el diseño antes de tocar. | medio |
| 17 | ✅ **CSV curado por CLI** | `catalogo_lotes`, fuente `curado`, formato `catalogo_curado_v1`, `make catalogo-curado` (genera) y `make catalogo-importar` (valida en seco + importa), hashes. | medio |
| 18 | ✅ **ETL desde el panel** | `etl_ejecuciones`, registro de definiciones, worker `web` y `local`, API `/v1/admin/etl`, sección ETL con formularios generados, cancelación, auditoría, subida del CSV por el panel. | grande |
| 19 | 📋 **Dashboard de admin** (planificado) | `eventos` genéricos + tarjetas de precios/usuarios/invitaciones, rankings, mapa de zonas y exportación programada de eventos (§11). | grande, en 3 partes (19a, 19b, 19c) |

**Orden y por qué:** 13 → 14 → 15 → 16 → (release) → 17 → 18. Hasta el 16 inclusive el release
sale con datos normalizados, un tablero para revisar lo dudoso, una forma de completar lo
descartado y el moderador listo. Para cargar la base de producción **no hace falta** el panel de
ETL: se corre el ETL desde tu Mac con `DATABASE_URL` remoto (es lo que hace el worker local de
todos modos), así que 17 y 18 pueden ir después del primer reparto sin bloquearlo.

## 11. Dashboard de admin como landing (corte 19, planificado)

Estado: diseñado el 2026-11-24 (pedido del dueño). Va en tres partes, cada una en su rama y PR:
**19b hecho** (rama `feat/eventos-app`, ver «Hecho en 19b» al final de §11.7); **19a hecho** (rama `feat/dashboard-19a`, ver «Hecho en 19a»); **19c hecho** (rama `feat/dashboard-19c`, ver «Hecho en 19c»). El
dueño eligió este orden: 19b primero, probarlo en local/offline, y después 19a y 19c.

> **Versionado:** el esquema de versiones de release cambió. Lo que este plan llama «v0.0.1» y
> «v0.0.2» son **nombres históricos de planes**, no versiones vigentes: la 0.0.1 es una compilación
> vieja. El próximo release es **0.1.x**. La app que **emite eventos** (§11.2) sale en esa línea;
> la **validación colaborativa** (y por lo tanto la tarjeta «precios validados») probablemente en
> **0.2.x o posterior**. El panel y el backend no dependen de la versión de la app: se despliegan solos.

### 11.1 Qué muestra (la pantalla de inicio del panel)

| Bloque | Qué cuenta | De dónde sale | Estado de los datos |
|---|---|---|---|
| **Precios cargados** | Por hora, día, semana y mes | `precios.created_at` | ya hay |
| **Precios validados** | Igual que arriba | `validaciones` | queda en **0** hasta que exista la validación colaborativa (0.2.x+); la tarjeta se dibuja igual para no rehacerla |
| **Usuarios activos anónimos / registrados** | Distintos usuarios que cargaron un precio, un producto nuevo o una sugerencia en los últimos N días (N configurable, 7 por defecto) | `precios` + `auditoria_admin` + `sugerencias_catalogo` + `usuarios.es_anonimo` | ya hay |
| **Invitaciones** | Enviadas, aceptadas, pendientes (y vencidas, que no son pendientes) | `invitaciones` | ya hay |
| **Productos estrella** | Los EAN más escaneados por **usuarios distintos** (no por escaneos repetidos de uno solo) | `eventos` (`producto.escaneado`) | vacío hasta que la app emita eventos |
| **Rankings de usuarios** | Quién más carga productos nuevos, precios y sugerencias (alias, nunca email) | `productos_canonicos` (origen manual) / `precios` / `sugerencias_catalogo` | ya hay |
| ~~Zonas con más actividad~~ | Mapa con celdas en verde según los precios cargados | `precios` + `locales.ubicacion` | **Postergado** (2026-11-25): futuro corte, con más datos y más usuarios; los tiles consumen recursos |

- **«Usuario activo»** (decidido el 2026-11-24) = el que **hizo una carga en los últimos 7 días**, y
  «carga» es cualquiera de: **un precio**, **un producto nuevo** o **una sugerencia de cambio**. Los dos
  últimos solo los pueden hacer moderadores y admins, pero también cuentan. Es **configurable**:
  `config.dashboard_activo_dias` (por defecto 7). Se cuenta por usuarios distintos (uno que hizo las tres
  cosas cuenta una vez), separados anónimos / registrados (`usuarios.es_anonimo`). Fuentes: `precios`,
  `productos_canonicos` (altas manuales: `auditoria_admin` con `producto.crear`) y `sugerencias_catalogo`.
  Más adelante se podrá ampliar (abrir la app, escanear…) con los eventos de §11.2; por eso `app.abierta`
  queda preparado pero **no** cambia esta definición hasta que se decida.
- **«Mejores precios»** empieza como **densidad de precios cargados** por zona (lo pedido). «Precio
  relativo al promedio» (zona más barata) es una **segunda etapa**: hay que normalizar por producto
  para no comparar un aceite con un fideo. Queda anotado, no se diseña ahora.
- **Orden de las partes:** **19a** tarjetas y series que ya tienen datos (precios, invitaciones,
  usuarios activos por precios, rankings) + zona horaria; **19b** `eventos`, endpoint, cambio
  mínimo en la app y productos estrella; **19c** exportación
  (manual y programada; el mapa de zonas se sacó el 2026-11-25, ver 19c). Solo 19b toca `app/`.

### 11.2 Eventos: una tabla genérica, no una por concepto

Hoy el único evento que querés guardar es el escaneo, pero van a aparecer más. Se arma **una tabla
genérica** y un **registro de tipos** (como el registro de ETL), así un evento nuevo es agregar una
entrada en código, no una migración.

```
eventos
  id            bigint generated always as identity primary key
  tipo          text        not null  check (tipo ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$')   -- 'producto.escaneado'
  ocurrio_en    timestamptz not null  default now()        -- el instante (UTC), lo pone el servidor
  usuario_id    uuid        references usuarios (id) on delete set null
  entidad       text        null      -- 'producto', 'local'… (para agrupar sin abrir el json)
  entidad_ref   text        null      -- el EAN, el id del local…
  datos         jsonb       not null  default '{}'         -- lo propio de cada tipo
  indices: (tipo, ocurrio_en), (tipo, entidad_ref), (usuario_id, ocurrio_en)
```

- **Registro de tipos** (`backend/app/services/eventos.py`): por cada tipo, qué `datos` acepta
  (esquema Pydantic), si lo puede mandar la app (`desde_app`) o solo el backend, y si cuenta como
  «actividad» del usuario. Un tipo desconocido se rechaza (400): nadie llena la tabla con basura.
- **Tipos iniciales:** `producto.escaneado` (`datos: {ean, encontrado: bool}`) y `app.abierta`.
  Candidatos futuros, **sin implementar**: `producto.consultado`, `local.consultado`,
  `precio.visto`. Agregarlos no cambia el esquema.
- **Endpoint:** `POST /v1/eventos` recibe una **lista** (hasta 50) para que la app pueda juntar y
  mandar de a tandas sin gastar batería. Autenticado, con rate limit. El instante lo pone el
  servidor; si la app manda el suyo (`ocurrio_en_cliente`), se guarda aparte en `datos` y nunca se usa
  para agrupar (los relojes de los celulares mienten).
- **Privacidad:** el evento lleva el id del usuario y nada más personal (sin ubicación, sin texto
  libre). Los tipos nuevos pasan por esa misma revisión antes de entrar al registro.
- **Retención:** `config.eventos_max_filas` (por defecto **100 000**, configurable). Al pasarlo, el
  dashboard avisa y ofrece exportar (§11.4). Si hace falta más adelante, la tabla se puede
  particionar por mes sin cambiar el código (por eso el índice empieza por `tipo, ocurrio_en`).

### 11.3 Zona horaria: UTC por dentro, Buenos Aires solo al mostrar

**Estado verificado el 2026-11-24:** la base local tiene `timezone = UTC` y **no hay ninguna columna
`timestamp without time zone`** (todas son `timestamptz`). Pero el pool del backend **no fija** la zona
de la sesión: hoy depende de lo que traiga el servidor. Ese es el hueco a cerrar, porque con otro
proveedor podría ser otra.

Reglas (se escriben también en el Doc 2, «Tiempo y zona horaria», porque valen para todo el proyecto):

1. **Todo instante es `timestamptz`.** Nunca `timestamp` sin zona. Un test recorre
   `information_schema.columns` y falla si aparece una (así una migración futura no la cuela).
2. **La sesión siempre en UTC, la fijamos nosotros.** El pool del backend y la conexión de los ETL
   (`etl/comun/catalogo.py::conectar`) crean cada conexión con `server_settings={"timezone": "UTC"}`.
   Así el resultado **no depende** del valor por defecto de Supabase ni del proveedor al que nos
   mudemos. Al arrancar, el backend verifica `show timezone` y, si no es UTC, lo registra en el log.
3. **Dónde ocurre la conversión a hora argentina: una sola vez, al armar la respuesta del dashboard.**
   La zona sale de `config.panel_zona_horaria` (por defecto `America/Buenos_Aires`) y se valida contra
   `pg_timezone_names`. El resto del sistema no sabe que existe.
4. **Por qué no hay riesgo de «argentino a argentino»:** la doble conversión solo pasa con valores
   **sin** zona (`timestamp`), que se reinterpretan según la zona de quien los lea. Con `timestamptz` el
   valor es un instante absoluto y `ts AT TIME ZONE 'America/Buenos_Aires'` solo lo **expresa** en hora
   local; no lo reinterpreta. Aun así, para que no haya que confiar en eso, la regla 1 y la 2 impiden
   que exista un valor ambiguo.
5. **Cómo se agrupa por hora/día/semana/mes:** el backend recibe `granularidad` y la zona, y calcula
   `date_trunc(g, ts AT TIME ZONE zona) AT TIME ZONE zona`, o sea que cada bucket **vuelve como un
   instante UTC** (`inicio_utc`, ISO-8601 con `Z`) que es el comienzo del bucket local. El panel solo
   formatea con `Intl.DateTimeFormat(..., {timeZone})`. Un «día argentino» arranca a las 00:00
   GMT-3 = 03:00 UTC: agrupar por día **UTC** y rotular como argentino daría días corridos 3 horas,
   y por eso el día se agrupa en la zona, no en UTC. Argentina no tiene horario de verano hoy, pero
   el cálculo no lo asume (una zona con DST también da buckets correctos, de 23 o 25 horas).
   La semana empieza el lunes (ISO).
6. **Tests que lo fijan** (Postgres real): (a) datos sembrados cerca de la medianoche argentina caen
   en el día correcto; (b) el resultado es idéntico con `set timezone = 'UTC'` que con
   `'America/Buenos_Aires'` y `'Asia/Tokyo'` en la sesión; (c) el test de «sin columnas `timestamp`»;
   (d) la zona inválida da 422.

### 11.4 Exportar y vaciar eventos (manual y programado)

Objetivo: que la tabla no crezca sin límite **y** que no dependa de una persona acordarse.

- **Formato:** el mismo criterio que los demás exports (Doc 9): `.zip` con `eventos.csv` y un `LEEME.txt`,
  nombre sin extensión, hash del contenido. Columnas: `id, tipo, ocurrio_en (UTC, ISO-8601 con Z),
  usuario_id (uuid), entidad, entidad_ref, datos (json)`. Es un export **de análisis**, no de
  intercambio: lleva ids de usuario (es el dato que se quiere analizar), así que no se comparte afuera
  sin anonimizar; el `LEEME.txt` lo dice.
- **ETL nuevo** `eventos_exportar` (parámetros: `tipo` opcional, `hasta` opcional, `borrar`
  sí/no). Corre por la cola de siempre y queda en el historial y la auditoría.
- **El borrado es seguro por construcción:** se exporta todo lo que tenga `id <= N` (N fijado al
  empezar), se comprueba que el archivo quedó guardado **y** que su hash/cantidad coinciden, y recién
  ahí se borran **solo** esas filas, en una transacción, y se anota en `eventos_exportaciones` (id,
  tipo, rango de ids, filas, sha256, nombre, cuándo). Si algo falla, no se borra nada.
- **Dónde queda el archivo (decidido el 2026-11-24): un bucket de Supabase Storage para arrancar.** El
  disco del backend desplegado (Fly) es efímero, así que un export programado no puede quedar ahí. Se
  accede por la **API S3** (no por el SDK de Supabase), así que mudarse a otro almacenamiento
  S3-compatible es cambiar variables de entorno (`EXPORT_S3_ENDPOINT`, `_BUCKET`, `_KEY`, `_SECRET`).
  El panel lista las exportaciones y deja descargarlas; el worker local sigue pudiendo escribir en
  `ETL_EXPORT_DIR`. El código habla con una interfaz mínima de «almacén» (guardar, leer, listar,
  borrar) con dos implementaciones: S3 y disco.
  - **Cobertura gratuita** (según la documentación de Supabase al 2026-11-24, a reconfirmar en
    <https://supabase.com/pricing> antes de depender de ella): el plan Free trae **1 GB** de archivos,
    **50 MB** por archivo y **5 GB** de egress (descargas). Un evento pesa unos 100–200 bytes en CSV, así
    que 100 000 eventos son ~10–20 MB y el `.zip` unos 2–5 MB: **1 GB alcanza para cientos de
    exports**. Lo que sí hay que respetar es el tope de 50 MB por archivo: `eventos_exportar` parte el
    export en varios `.zip` si hace falta (`config.eventos_export_filas_por_archivo`, por defecto
    500 000), y cada parte registra su rango de ids. Cuidado aparte: en el plan Free los proyectos se
    **pausan tras una semana sin actividad**; para producción no es opción, pero no cambia este diseño.
  - **«Que nada falle al mudarse»:** el export hace siempre la misma comprobación, sea cual sea el
    almacén: sube el archivo, lo **vuelve a leer**, compara tamaño y sha256 y **recién ahí** borra las
    filas. Se agrega `make almacen-probar` (y un botón en el panel) que hace esa ida y vuelta con un
    archivo de prueba: se corre al configurar un almacén nuevo y antes de activar la programación. Si
    falla, los eventos no se tocan. Tests: con un servidor S3 local (un S3 alternativo en el `docker compose` de
    desarrollo) y con la implementación de disco, el mismo conjunto de pruebas.
- **Programación:** no hay un planificador en el proyecto. Se agrega una tabla genérica
  `etl_programaciones` (ETL, parámetros, expresión cron **interpretada en UTC**, activa, última y
  próxima corrida, última ejecución) y un ciclo liviano dentro del proceso web que, con
  `pg_try_advisory_lock` (para que con varias réplicas corra una sola), encola en la **misma** cola
  `etl_ejecuciones`. Sirve para eventos y también para cualquier otro ETL. Se administra desde la
  sección ETL; el panel muestra la hora en Buenos Aires y guarda UTC. No se usa `pg_cron` a propósito:
  ata el proyecto a una extensión del proveedor (regla de «nada acoplado a Supabase»).
- **Disparador por umbral:** además del cron, si `eventos_max_filas` se supera y la programación está
  activa con «exportar al pasar el umbral», el ciclo encola el export. Si no, el dashboard solo avisa
  (banner con el conteo y el botón «Exportar ahora»).

### 11.5 API, permisos y pantalla

- `GET /v1/admin/dashboard/resumen?desde=&hasta=` (tarjetas), `GET /v1/admin/dashboard/series?metrica=precios|validaciones|activos&granularidad=hora|dia|semana|mes&desde=&hasta=&zona=`,
  `GET .../rankings?tipo=productos|precios|sugerencias`, `GET .../estrellas`. Sin tablas precalculadas: con el volumen actual alcanzan consultas
  directas con los índices que ya hay; si un día pesan, se agregan vistas materializadas sin cambiar la API.
- **Permiso nuevo** `dashboard.ver` (admin; el moderador no). Los datos de usuarios muestran **alias**.
- **Mapa de zonas: postergado** (2026-11-25, pedido del dueño). Se había hecho en 19c (Leaflet + grilla
  PostGIS) y se quitó: aporta poco con tan pocos datos y los tiles gastan recursos. Vuelve como corte
  propio cuando haya más datos y usuarios, junto con la decisión del proveedor de teselas (ver «Abiertas»).
- **Landing:** el panel abre en el dashboard (hoy abre en Locales); el resto del menú queda igual.
  Selector de período (hoy, 7 días, 30 días, mes, rango) y de granularidad.

### 11.6 Fuera de alcance de este corte

Validación colaborativa (hasta 0.2.x), «precio relativo al promedio», alertas por mail, dashboards
públicos y particionado de `eventos` (se deja preparado, no se hace).

### 11.7 Orden de trabajo y qué debe quedar probado

1. **19a (sin tocar la app):** reglas de zona horaria (pool y ETL en UTC, test de columnas, aviso al
   arrancar) + `GET /dashboard/*` de precios, validaciones, invitaciones, rankings y zonas + landing.
2. **19b (toca `app/`, va con el release 0.1.x):** migración `eventos`, registro de tipos,
   `POST /v1/eventos`, la app emite `producto.escaneado` y `app.abierta` (en lote, tolerando estar
   sin red: si falla, descarta, **nunca** bloquea escanear) y productos estrella.
3. **19c:** `eventos_exportar`, `eventos_exportaciones`, `etl_programaciones` y el ciclo, bucket de
   exportaciones, banner por umbral.

Cada parte: tests contra Postgres real, `make lint` y `make test` en verde, docs al día y PR propio
(yo no mergeo).

**Hecho en 19b** (2026-11-24):

- Migración `20261130000001_eventos.sql` (tabla e índices como en §11.2, con RLS activado y sin
  políticas: solo el backend la toca). Config nueva: `eventos_max_filas` (100 000) y
  `max_lotes_eventos_por_hora` (120), con default en `services/config.py` y en `seed.sql`.
- `services/eventos.py` (registro: esquema de `datos` con `extra="forbid"`, `desde_app`,
  `cuenta_como_actividad` —hoy falso en todos—, entidad/ref) y `POST /v1/eventos`. Reglas nuevas en el
  catálogo `services/reglas.py`: `evento_tipo_desconocido` (400) y `evento_datos_invalidos` (422).
- **Decisiones de más:** el lote es todo o nada; el rate limit es por **lotes** por usuario por hora
  (reusa `ratelimit.limitar`, en memoria como el resto del anti-spam) y no por eventos; el `ean` del
  escaneo se valida de 8 a 14 dígitos (un código escaneado no hallado en el catálogo igual es válido).
- **Zona horaria (reglas 1 y 2 de §11.3):** pool y ETL en UTC, `verificar_utc` al arrancar y test de
  columnas `timestamp`. Las reglas 3 a 6 (conversión, buckets) siguen para 19a.
- **App:** `ColaEventos` en memoria (tope 200, lotes de 50, envío ~5 s después del primer evento nuevo y al irse a segundo plano,
  timeout de 10 s por lote, descarte sin reintentar). `app.abierta` se anota al arrancar el proceso (no
  al volver de segundo plano). `producto.escaneado` se anota **solo si se escaneó con la cámara** (no al
  tipear el código) y **cuando se sabe `encontrado`** (200 → true, 404 → false); si el pedido falla por
  red no se anota nada. El pedido es «silencioso»: no prende «Despertando servidor…».
- **Ajustes tras la primera prueba en el celular (2026-11-24):**
  - `producto.escaneado` ahora lleva `via` (`camara` | `manual`, opcional): un código **tipeado** también
    se anota, porque un EAN inexistente no se puede escanear y no había forma de probar `encontrado:
    false`. El dashboard de productos estrella podrá contar solo `camara`, o ambas.
  - `app.abierta` lleva datos del celular, todos opcionales y **sin pedir permisos al usuario**:
    `app_version`, `android`, `sdk`, `marca`, `modelo`, `idioma` y `red` (`wifi|movil|ethernet|otra|ninguna`).
    Nunca: ubicación, nombre de la red (SSID), batería ni identificadores del aparato. `red` usa
    `connectivity_plus`, que declara `ACCESS_NETWORK_STATE` (permiso «normal» de instalación, sin cartel).
  - **Envío:** la cola manda solo ~5 s después del primer evento nuevo (antes: cada 60 s o al irse a
    segundo plano, y por eso los eventos «aparecían» recién al salir de la app). También sigue mandando al
    pasar a segundo plano. Si falla, se descarta y queda una línea en el log (`adb logcat | grep eventos`).
  - Los tests de backend borran los eventos que crean (comparten base con el celular).
- **Pendiente de 19b: productos estrella** (`GET .../estrellas`) van con el dashboard (19a/19c), porque
  dependen del endpoint `/dashboard/*`; acá solo se guardan los datos.
- Qué no se probó: nada contra un celular real ni contra el contenedor del backend (los tests de
  backend corren la app en proceso contra Postgres real); ver los pasos manuales del PR.

**Hecho en 19a** (2026-11-24; revisión del diseño con el dueño antes de implementar):

- **Decisiones tomadas en la revisión** (cubren también al 19c):
  - **Invitaciones aceptadas, con serie en el tiempo.** `invitaciones.usada_at`/`usada_por_auth`
    guardaban solo el **último** uso (se pisaban), así que en un código de varios usos se perdía el
    historial. Migración `20261201000001_invitaciones_usos.sql`: una fila por uso (`invitacion_id`,
    `auth_id`, `usada_en`; `on delete set null` para que borrar una invitación no borre la serie).
    Los usos viejos entran como una fila por invitación (lo único que se conocía). `consumir` devuelve
    un `Uso`; `devolver` baja el contador y borra esa fila si el alta falla.
  - **Productos estrella:** cuentan escaneos con cámara **y** tipeados, con filtro `via` opcional.
  - **Almacén de exportaciones (19c):** S3-compatible. Producción: bucket de Supabase Storage (1 GB en
    el plan Free); mudarse = cambiar `EXPORT_S3_*`. Desarrollo y tests: el **Storage local de Supabase**
    (ya corre con `make up`, API S3 en `:54321/storage/v1/s3`, claves en `supabase status`). **MinIO**
    se propuso como perfil opcional del compose (`--profile s3-alt`) y servicio de CI, para probar que no
    dependemos de Supabase; al implementarlo (19c) resultó que ya no publica imágenes públicas y se usó
    **SeaweedFS** en su lugar (ver «Hecho en 19c»). El disco (`ETL_EXPORT_DIR`) queda para el worker local y los tests.
  - **Cliente S3:** `boto3` en un hilo (`asyncio.to_thread`, como el ETL), no `aioboto3`: más simple y
    estable para un volumen chico.
  - **Programaciones (cron) en la sección ETL**; los números sueltos (`eventos_max_filas`,
    `eventos_export_filas_por_archivo`, `panel_zona_horaria`, `dashboard_*`) en Configuración.
- **API** `GET /v1/admin/dashboard/` `resumen | series | rankings | estrellas`, permiso `dashboard.ver`
  (solo admin). `series` acepta `metrica=precios|validaciones|activos|invitaciones` (la de invitaciones
  es nueva, posible gracias a `invitaciones_usos`), `granularidad=hora|dia|semana|mes`, `desde`/`hasta`
  (ISO-8601, UTC con Z; por defecto 7 días) y `zona`. Los buckets vacíos salen en 0 y `activos` separa
  anónimos y registrados. Máximo 1000 barras por serie (`periodo_invalido`, 422).
- **Definiciones:** «usuario activo» = hizo una carga (precio, producto nuevo —`auditoria_admin` con
  `producto.crear`— o sugerencia) en los últimos `config.dashboard_activo_dias` (7) hasta **ahora**, sin
  importar el período elegido. Invitaciones: `emitidas` (códigos), `disponibles`, `usadas` (`usos >=
  usos_max`), `vencidas` (sin agotar y con `vence` pasado) y `aceptadas` (**usos**, en el período y en
  total). Rankings por alias (nunca email): `precios`, `productos` (altas manuales) y `sugerencias`.
- **Zona horaria (reglas 3 a 6 de §11.3):** `config.panel_zona_horaria` (por defecto
  `America/Buenos_Aires`), validada contra `pg_timezone_names` por nombre exacto (no valen siglas como
  ART; `EST` sí existe en la base de zonas). Una zona inválida da 422 `zona_invalida` (también al
  editarla en Configuración). El bucket se calcula con `date_trunc(unidad, ts AT TIME ZONE zona) AT TIME
  ZONE zona` y vuelve como instante UTC. Tests (`test_dashboard.py`): medianoche argentina, resultado
  idéntico con la sesión en UTC, Buenos Aires y Tokyo, semana ISO desde el lunes, hora y mes.
  Límite conocido: en zonas con horario de verano, las barras por **hora** de la hora repetida se
  juntan (Argentina no tiene).
- **Panel:** el inicio es el dashboard (tarjetas, serie con barras, rankings, productos estrella),
  con selector de período (hoy, 7 días, 30 días, mes, rango) y de granularidad. «Hoy» y «mes» arrancan
  a la medianoche de la zona del panel, no del navegador. Sin librerías de gráficos (barras en CSS).
- `make help` lista cada target con su descripción (lee los `## ...` del Makefile).
- Qué no se probó: el panel en un navegador real contra el contenedor (se probó contra un backend
  local de la rama en otro puerto); el mapa y la exportación son del 19c.

**Hecho en 19c** (2026-11-24):

- **Mapa de zonas: quitado** (2026-11-25). Se había hecho (GeoJSON + Leaflet) y se sacó a pedido del dueño: con
  pocos datos no aporta y los tiles gastan recursos. Se eliminaron `GET /v1/admin/dashboard/zonas`, Leaflet
  y las config `dashboard_celda_m` y `dashboard_celda_min_precios`. Queda como futuro corte.
- **Almacén** (`etl/comun/almacen.py`): interfaz mínima (`asegurar`, `guardar`, `leer`, `listar`,
  `borrar`) con **S3** (`boto3`, path-style, sirve para Supabase Storage, SeaweedFS, MinIO, R2…) y **disco**. Se elige
  por entorno: `EXPORT_S3_ENDPOINT/_BUCKET/_KEY/_SECRET/_REGION`; sin endpoint, `ETL_EXPORT_DIR`.
  `verificar` sube, **relee** y compara tamaño y sha256; `probar` hace esa ida y vuelta con un archivo de
  prueba y lo borra: `make almacen-probar` y el botón «Probar almacén» (`POST /v1/admin/almacen/probar`,
  502 `almacen_fallo` con explicación si falla). `make up` completa las `EXPORT_S3_*` con el Storage S3
  local de Supabase (se comprobó que `boto3` funciona contra él, incluso creando el bucket).
- **S3 alternativo** opcional en el compose (perfil `s3-alt`, `make s3-alt-up` / `s3-alt-down`; API en
  `:8333` es solo la API S3 y responde XML; para **ver** los archivos está el navegador del filer en
  `http://localhost:8888/buckets/`, y el estado del cluster en `:9333`; cualquier clave sirve). **No es MinIO:** MinIO dejó de publicar imágenes públicas
  (Docker Hub y quay.io dan «access denied», comprobado el 2026-11-24), así que se usa **SeaweedFS**
  (`chrislusf/seaweedfs`, versión fija). No arranca con `make up`. Los tests corren el mismo conjunto contra
  **disco, Storage local y el S3 alternativo** (los S3 se saltean con aviso si no responden); CI levanta el
  alternativo antes de los tests.
- **ETL `eventos_exportar`** (ejecutor `web`; parámetros `tipo`, `hasta` —fin de ese día UTC— y `borrar`):
  lee los eventos, **fija sus ids**, arma `.zip` (`eventos.csv` + `LEEME.txt`, deterministas) partidos cada
  `config.eventos_export_filas_por_archivo` (500 000), sube y **relee** cada parte y, con **todas**
  verificadas, anota `eventos_exportaciones` y borra **solo esos ids** en una transacción. Se borra por
  ids y no por «`id <= N`» porque un evento confirmado tarde con un id menor se perdería (hay un test).
  Si algo falla antes, no se borra nada. `GET /v1/admin/eventos/exportaciones` lista y
  `.../{id}/descargar` baja el archivo desde el almacén (queda auditado).
- **Programaciones:** tabla `etl_programaciones` (cron en **UTC**, `services/cron.py`: 5 campos, `*`,
  listas, rangos, pasos; sin nombres ni atajos), CRUD en `/v1/admin/etl/programaciones` (capacidad nueva
  `etl.programar`; los ETL que piden un archivo no se pueden programar) y un ciclo del backend cada 30 s
  (`services/programaciones.py`) que encola en la misma cola `etl_ejecuciones` con
  `pg_try_advisory_xact_lock` (con varias réplicas corre una sola). No apila: si la anterior sigue en cola o
  corriendo, se salta. **Umbral:** con «al superar el tope», una programación activa de `eventos_exportar`
  encola cuando `eventos` pasa de `eventos_max_filas` (como mucho una vez por hora). Lo que encola el
  sistema queda con `creado_por` nulo y en la auditoría como `programacion.ejecutar`.
- **Panel:** sección ETL con «Almacén de exportaciones» (probar + lista de exportaciones con descarga) y
  «Programaciones» (la hora se muestra en la zona del panel, se guarda UTC); el dashboard muestra un banner
  con «Exportar ahora» cuando se pasa el tope de eventos (el `resumen` trae `eventos`).
- Config nueva: `eventos_export_filas_por_archivo`.
- Los tests apagan el ciclo (`PROGRAMACIONES_ACTIVO=false` en `conftest.py`) y llaman a `vuelta` a mano.
- Qué no se probó: el panel contra los contenedores de `make up` (se probó contra un backend local de la
  rama, incluido un export real por el ejecutor web al Storage S3 local); Supabase Storage de **producción**
  y su tope de 50 MB por archivo (la partición lo respeta por filas, no por bytes: a ~200 bytes por evento,
  500 000 filas son ~100 MB de CSV y ~10–25 MB comprimidos; si hiciera falta, bajar el valor).

## 12. Cambio de alias (corte 21)

Pedido del dueño (2026-11-25). Diseño: `docs/superpowers/specs/2026-11-25-alias-editable-design.md`; plan:
`docs/superpowers/plans/2026-11-25-alias-editable.md`. Resumen técnico en el Doc 2, «Alias del usuario».

- **Estado:** ✅ hecho (rama `feat/alias-editable`, un PR; el dueño prueba en el celular antes de mergear).
- **Qué entra:** lápiz junto al alias en el inicio (edición en el lugar, se guarda al salir del campo),
  `POST /v1/me/alias`, interruptor por rol en `config` (`alias_editable_por_rol`), tope diario, reservados y
  lista de bloqueo, historial en tabla propia con trigger y su vista en la ficha del usuario del panel.
  Las listas de `config` ahora se editan en el panel como JSON.
- **Decisiones del agente que el dueño puede cambiar** (todas en `config` salvo el formato): abierto solo
  a moderador y admin; 3 cambios por día; el alias viejo se libera; sin lista de ofensivos por defecto
  (la arma el dueño en `alias_bloqueados`); el admin puede corregir cualquier alias desde el panel.
- **Migración con datos viejos:** si ya había alias repetidos, el más viejo conserva el nombre y los demás
  reciben un sufijo con el comienzo de su id (queda anotado en el historial como cambio del sistema).
- **Pendiente / futuro:** mostrar el alias a otros usuarios (rankings) y una moderación más fina de
  ofensivos; fusión de perfiles (reasignar por `usuario_id`) si algún día hace falta.

## Decisiones

**Tomadas**

1. Alta de local por cualquier usuario, sin verificar, **solo para pruebas** y
   controlada por `config.alta_locales_abierta`. El Doc 1 no cambia.
2. Anti-duplicados **sin bloqueo por distancia** (locales contiguos), bloqueando
   solo nombre casi idéntico a muy poca distancia.
3. Límite de locales nuevos por día: **50**, en `config`.
4. Invitaciones: **un código compartido**.
5. ETL: **uno por fuente**, todo el mundo (no solo Argentina), con lista de
   conflictos para revisión manual.
6. Roles: empezar con una columna `rol` detrás de un módulo de capacidades, para
   migrar a tablas sin tocar endpoints (§1).

7. **`applicationId` = `dev.crulises.almacenero`** (dominio `crulises.dev` al revés). Se
   cambia en el corte 10, antes del primer release firmado; el grupo cerrado desinstala
   la versión vieja (hoy `ar.almacenero.almacenero`) e instala la nueva.
8. **Hosting: Fly.io** (cuenta creada, créditos iniciales). Se mantienen abiertas las
   alternativas (p. ej. Cloudflare Pages para el panel estático) y se vigila el costo
   desde el inicio: hay más proyectos de hobby por venir. Se elige lo más barato
   mientras no complique mucho el despliegue.
9. **Dominio y rutas:** todo lo que se accede por navegador va detrás de
   `almacenero.crulises.dev` separado por rutas (`/admin`, y las que vengan); el backend
   (que la app usa, sin interfaz) va en `almacenero-api.crulises.dev`. La raíz
   `crulises.dev` queda como firma/currículum y cada proyecto de hobby cuelga de un
   subdominio propio.
10. **Timeout configurable + «Despertando servidor…» y `make backup` con simulacro**:
    se adelantan, en una rama propia y antes que el resto del corte 10.
11. **Atribuciones:** pantalla «Acerca de» desde un ícono ⓘ en la barra (versión, fuentes
    con su licencia y enlace, licencias de librerías con `showLicensePage`) y etiqueta
    «© OpenStreetMap» en el mapa; la tarjeta de versión/servidor/IP se muda ahí.
12. **Curación del catálogo:** corte propio, con ejemplos que reúne el dueño del proyecto
    (qué estandarizar y qué no gusta). Antes de usar el catálogo de forma permanente.

13. **Dashboard (corte 19): invitaciones con serie** (tabla `invitaciones_usos`), **productos estrella
    con ambas vías y filtro**, **almacén de exportaciones S3-compatible** (Supabase Storage en
    producción y en desarrollo local; S3 alternativo opcional —SeaweedFS— para probar portabilidad), **`boto3` en un hilo**,
    **programaciones en la sección ETL** y números sueltos en Configuración. Detalle en §11
    («Hecho en 19a»).

**Abiertas**

- **Proveedor de teselas del mapa (NO SE OLVIDE; aplica al mapa de la app y al futuro mapa de zonas del dashboard):** OSM público solo sirve para el grupo
  cerrado (política de uso de OSM: uso liviano, atribución, sin abuso). Decidir **antes de
  abrir la app a más gente**: proveedor con plan gratis (MapTiler, Stadia), Google Maps
  (paga pasado cierto uso) o **autohospedar** con Protomaps/PMTiles (un archivo servido
  desde Cloudflare R2, costo casi nulo). Tema para revisar en cada repaso de pendientes.
- **Estrategia de ramas y versiones:** definir una convención que alinee número de versión
  de la app (`APP_VERSION`), tags de git y releases del backend en Fly.
- **Setup del entorno en otra computadora:** documentar todo lo necesario (Docker,
  Supabase CLI, Flutter/Android, `flyctl`, etc.) para mover el entorno de desarrollo a
  cualquier máquina; se escribe con el corte 10.
- **Base de datos y pausa de Supabase gratis:** ver §7 «Elegir host»; si la pausa
  no es tolerable, evaluar Postgres en otro servicio (costo-beneficio).
- **Imágenes subidas por usuarios** (diferidas): compresión en el cliente y
  re-codificación en el servidor; moderación antes de publicar (§7).
- **Tamaño del catálogo en producción:** se decide tras medir la carga completa
  en local (§4). El catálogo de OFF sigue sin cargarse; SEPA de un día sí.

## Plan de escape: recrear todo en otro lugar

Hacerlo **antes de cargar datos reales** y repasarlo cada tanto.

- **Esquema:** migraciones SQL planas en `supabase/migrations/` (sin nada propio de
  Supabase en el código). Probar de vez en cuando que levantan en un Postgres
  común con PostGIS y `pg_trgm`.
- **Auth:** el backend valida el JWT con `JWT_SECRET`/`JWKS_URL`/`AUTH_URL`. Hoy
  los emite GoTrue; irse implica o desplegar GoTrue aparte o emitir los tokens
  desde el propio backend. Es el punto más acoplado: decidirlo y probarlo antes
  de salir.
- **Datos:** `pg_dump` periódico (lógico, `make backup`) a un lugar fuera de
  Supabase, más una prueba de restauración en un Postgres limpio (`make restore-test`).
  Los ETL (`make etl-*`) regeneran el catálogo, así que el backup crítico son usuarios,
  locales y precios cargados.
  - **Procedimiento.** (1) `make backup` → `backups/almacenero-<fecha>.dump` (+ `.conteos`
    con las filas de locales, productos, precios y usuarios; la carpeta no va a git).
    (2) `make restore-test` → crea una base temporal `almacenero_restore_test` en el mismo
    servidor, restaura el último dump, verifica que los conteos coincidan y la borra. Si
    imprime «Simulacro OK», ese backup sirve. Hacerlo con cada backup que importe y
    **siempre antes de un release**. Copiar el `.dump` a un lugar fuera de la máquina
    (otro disco, un bucket privado): un backup en el mismo disco no es un backup.
  - **Restaurar de verdad** (en otro Postgres): es lo mismo que hace el simulacro, sobre
    una base **vacía** nueva: crear las extensiones (`postgis`, `pg_trgm`, `unaccent`),
    `pg_restore --no-owner --no-privileges -f - <dump> | grep -Ev '^(SET
    transaction_timeout|CREATE SCHEMA public;)' | psql <url> -v ON_ERROR_STOP=1
    --single-transaction` (los porqués de los filtros, en `docs/03`) y apuntar el backend
    con `DATABASE_URL`. Esta ruta está probada solo contra el Postgres local; el simulacro
    en el Postgres final de producción queda para el corte 10. **Nunca** restaurar sobre la
    base real en uso.
  - **Lo que el backup NO cubre:** `auth.users` de Supabase Auth (ver «Auth» arriba) y las
    variables de entorno/secretos.
- **Storage (cuando haya fotos):** cliente S3-compatible detrás de una interfaz,
  con el bucket configurable por variables de entorno.
- **Config:** todo por variables de entorno (`.env.example` al día), imágenes
  Docker reproducibles, y la guía de deploy en `docs/`.
- **Simulacro:** un día antes del release, restaurar un backup en otro Postgres y
  apuntar el backend con `DATABASE_URL`; anotar lo que falle en el doc 03.

## Documentación a actualizar al ejecutar el plan

- Doc 1: invitaciones y roles (el alta de locales por usuarios **no**: es solo
  un interruptor de prueba).
- `CLAUDE.md`: alcance de v0.0.2 (hoy solo describe v0.0.1).
- `docs/03-problemas-soluciones.md`: lo que vaya apareciendo en cada corte
  (como hasta ahora).

## Versión del APK y pantalla de información (corte 9, ajuste)

**Versionado.** La serie (`0.0`, `0.1`, …) es el `version:` de `app/pubspec.yaml`: se
cambia a mano cuando se cierra un ciclo de pruebas. El último número sube solo en cada
`make apk` (`0.0.1`, `0.0.2`, …) y vuelve a 0 al cambiar de serie (`0.1.0`, `0.1.1`, …).
`app/tool/version.sh` lleva la cuenta en el `.git` compartido (no en el árbol de
trabajo) para no generar cambios ni conflictos entre worktrees. El APK lleva además el
commit (con `+local` si había cambios sin commitear) y la hora de compilación, y el
`versionCode` de Android sale de la fecha para que siempre se pueda instalar encima.

**Pantalla principal.** Una tarjeta al pie muestra, por ahora: versión y commit, hora de
compilación, URL del servidor, estado de `/v1/health` (con la demora, o el motivo) e IP
del celular por interfaz. Es la lista que se va puliendo según haga falta saber qué
esperar de un APK; candidatos: modo de acceso del servidor, versión del backend, última
sincronización.

## 12. Corte 20: flujo de carga y «Recientes» (cierra el release 0.1.x)

Diseño: `docs/superpowers/specs/2026-11-25-flujo-carga-recientes-design.md`. Rama `feat/flujo-carga-recientes`.
Qué quedó y dónde: Doc 2, «Flujo de carga y “Recientes” (corte 20)».

**Hecho:** volver a la ficha tras guardar un precio (sin pantalla de éxito), «Escanear otro»,
«Recientes» guardados en el celular con precio de referencia a hasta `radio_referencia_km`, «Sé el
primero en cargarlo» y bonus de karma `karma_primer_precio` (una vez por producto).

**Config nueva** (`services/config.py` y `supabase/seed.sql`): `radio_referencia_km` (300),
`karma_primer_precio` (5) y `recientes_max` (10: cuántos Recientes guarda y muestra la app).

**Decisiones del que construyó (el diseño las dejaba libres):**
- `referencia=true` en `precios/vigentes` además de subir el tope de `radio_m`: así la app no
  hardcodea el radio ni lo lee de la config.
- Recientes usa `shared_preferences` (dependencia nueva de la app); no es un dato sensible.
- Se muestra el local más cercano, no el más barato: es una guía de dónde y a cuánto, no un ranking.

**Probado:** backend (`tests/test_vigentes.py`, `tests/test_primer_precio.py`) contra Postgres real;
app (`test/recientes_test.dart`, `test/widget_test.dart`: navegación, Recientes, referencia, sin red).
