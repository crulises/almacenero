# Plan v0.0.2

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

**Abiertas**

- **Host del backend:** en evaluación por el dueño del proyecto.
- **Dominio:** lo busca el dueño del proyecto (uno solo, con subdominios).
- **`applicationId`:** decidir tras comprar el dominio y antes del primer release
  firmado (§7).
- **Proveedor de teselas del mapa:** OSM público solo sirve para el grupo
  cerrado; decidir (proveedor con plan gratis o propio) **antes de abrir la app**.
- **Timeouts de red configurables:** el tiempo de espera de `ApiClient` (hoy 15 s)
  pasa a ser un valor de configuración (`--dart-define` al compilar o ajuste
  remoto) para poder pasar a 30/60/90 s sin tocar código; con reintento y el
  mensaje «Despertando servidor…» cuando el primer pedido tarda. Se hace en el
  corte 10 (antes de repartir el APK).
- **Base de datos y pausa de Supabase gratis:** ver §7 «Elegir host»; si la pausa
  no es tolerable, evaluar Postgres en otro servicio (costo-beneficio).
- **Imágenes subidas por usuarios** (diferidas): compresión en el cliente y
  re-codificación en el servidor; moderación antes de publicar (§7).
- **Tamaño del catálogo en producción:** se decide tras medir la carga completa
  en local (§4).

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
  Supabase, más una prueba de restauración en un Postgres limpio. Los ETL
  (`make etl-*`) regeneran el catálogo, así que el backup crítico son usuarios,
  locales y precios cargados.
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
