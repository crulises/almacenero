# Doc 2 — Spec técnico

Arquitectura, stack y decisiones técnicas. Fuente de verdad para decisiones de
implementación.

## Arquitectura general

```
Flutter (Android)  →  API propia (FastAPI)  →  PostgreSQL
```

Supabase se usa en **modo headless**, como proveedor de servicios manejados:

- Postgres manejado.
- Auth (GoTrue).
- Storage (S3-compatible).

El cliente NO habla directo a Supabase (ni PostgREST, ni SDK, ni RLS como muro
principal). Todo pasa por el backend. Es deliberado: prioriza portabilidad por
sobre la magia nativa de Supabase. El uso headless de Supabase es legítimo y
soportado; lo que no se usa, no molesta, y la salida es limpia (dump de Postgres,
GoTrue reemplazable, Storage es S3).

## Dónde vive la lógica

- **Integridad → Postgres**: constraints, checks, triggers que impiden escribir
  datos inválidos (ej. karma no se setea a mano, fecha obligatoria, un precio
  apunta a exactamente un tipo de producto).
- **Negocio → backend FastAPI**: karma, cola de validación, chequeo de geofence,
  reglas de frescura. Portable: es lo que se lleva si se deja Supabase.

RLS queda como defensa en profundidad opcional, no como muro principal (el backend
usa service key del lado servidor).

## Stack

- App: Flutter, target Android. Dev con emulador Android.
- Escaneo EAN: paquete tipo `mobile_scanner`.
- Backend: FastAPI (Python async), Pydantic, OpenAPI automático.
- DB: PostgreSQL con PostGIS (consultas geo: locales cercanos, geofence).
- Auth: Supabase Auth. Providers v0.0.1: anónimo + Google + email. El backend
  valida el JWT (secreto / JWKS de Supabase). Dejar el cableado para más
  providers sin activarlos.
- Storage: Supabase Storage (S3-compatible → portable a MinIO).
- Dev local: Supabase CLI levanta el stack (Postgres, Auth, Storage, Studio) en
  Docker. Backend containerizado (Dockerfile + docker-compose).

## Imágenes

- Fotos de producto canónico: URLs de Open Food Facts, no se guardan.
- Fotos subidas por usuario (producto nuevo, genérico): a Supabase Storage,
  comprimidas y chicas.
- En v0.0.1 las imágenes subidas por usuario pueden diferirse.

## Migraciones y seeds

- Supabase CLI. Migraciones = archivos SQL plano versionados en
  `supabase/migrations/`, portables a cualquier Postgres.
- Seeds chicos (local del admin, config inicial) en `supabase/seed.sql`.
- Recrear la base = un comando. Repetible.
- Nada de datos grandes crudos commiteados al repo.

## ETL Open Food Facts

- Componente aparte (`etl/`, Python). NO es un seed.
- Flujo: ingesta de OFF → limpieza → normalización (tamaño/unidad a número +
  unidad) → carga al catálogo canónico.
- A futuro genera una versión propia del catálogo a medida que evoluciona.
- Esperar datos sucios e incompletos de OFF; el admin puede corregir y completar.

## Esquema de datos (primer borrador)

A refinar en implementación. Tablas núcleo:

- `usuarios`: id (uuid, pk), auth_id (ref al usuario de Supabase Auth), alias (editable; historial en
  `usuarios_alias_historial`, ver «Alias del usuario»),
  karma (int, default 0), created_at. El karma no se escribe directo; lo maneja
  el backend.
- `locales`: id, nombre, direccion, ubicacion (PostGIS geography point),
  medios_pago (jsonb: efectivo/debito/credito/transferencia/qr), recargo_tarjeta
  (jsonb: aplica bool, porcentaje), creado_por (admin), created_at.
- `productos_canonicos`: id, ean (unique), nombre, marca, tamano_valor (numeric),
  tamano_unidad (text), imagen_url, origen (off/manual).
- `items_genericos`: id, local_id (fk), categoria, descripcion, tamano_valor,
  tamano_unidad, created_at. Atado a un local. Desactivado por config en v0.0.1.
- `precios`: id, producto_canonico_id (fk, nullable), item_generico_id (fk,
  nullable), local_id (fk), precio (numeric), fecha (timestamptz), user_id (fk),
  created_at. CHECK: exactamente uno de canónico/genérico no nulo.
- `validaciones`: id, precio_id (fk), user_id (fk), resultado (ok/mal), created_at.
- `config`: clave, valor, rubro (nullable, para override por rubro). Tunables de
  admin: ventana de frescura, umbrales verde/amarillo/rojo, switches (pesables
  on/off, modo de acceso). La app la lee al arrancar y la cachea.

## Estructura del repo

Monorepo:

```
app/          Flutter (Android)
backend/      FastAPI
supabase/     config.toml, migrations/, seed.sql
etl/          pipeline de Open Food Facts
docs/         01-producto-vision.md, 02-spec-tecnico.md
CLAUDE.md
README.md
Makefile
.env.example
```

La carpeta `supabase/` es requisito del CLI, no acoplamiento. El código propio usa
`DATABASE_URL` y una capa `db` genérica; las migraciones son SQL plano.

## Comandos (Makefile)

Toda la operación vive en el Makefile. Objetivo: repetibilidad local y
portabilidad de CI.

- `make up` / `make down` — stack local.
- `make migrate`, `make seed`.
- `make test`, `make lint`, `make build`.
- `make help` — lista todos los targets con una línea de explicación (sale de los `## ...` del Makefile:
  al agregar un target, escribile su descripción ahí).

## Tiempo y zona horaria

Regla para todo el proyecto (decidida el 2026-11-24, a pedido del dueño; detalle y tests en
`docs/04` §11.3):

- **Todo instante se guarda en UTC y como `timestamptz`.** No existen columnas `timestamp` sin zona
  (un test lo verifica sobre `information_schema`).
- **No se confía en la zona por defecto del servidor de base de datos.** Cada conexión (backend y ETL)
  se abre con `timezone = UTC` fijado por nosotros, así cambiar de proveedor no cambia resultados.
- **La hora local (`America/Buenos_Aires`, configurable en `config.panel_zona_horaria`) se aplica una sola
  vez, al mostrar** (por ejemplo para agrupar por día argentino en el dashboard). La API devuelve
  instantes ISO-8601 con `Z`. Con `timestamptz` convertir a hora local solo la expresa; no la
  reinterpreta, y por eso no hay riesgo de convertir «argentino a argentino».
- Los relojes de los celulares **no** se usan para agrupar ni ordenar: el instante lo pone el servidor.
- **Cómo se hace cumplir** (implementado en el corte 19b): el pool del backend
  (`app/db.py::create_pool`) y las conexiones de los ETL (`etl/comun/catalogo.py::conectar`,
  `etl/ejecucion.py`) se abren con `server_settings={"timezone": "UTC"}`; al arrancar el backend
  verifica `show timezone` y, si no es UTC, lo deja en el log (`verificar_utc`). Los tests
  `test_zona_horaria.py` fallan si aparece una columna `timestamp without time zone`. La conversión a
  hora argentina para el dashboard se hizo en el corte 19a (ver abajo).
- **Dashboard (corte 19a):** `GET /v1/admin/dashboard/series` agrupa en la zona de `config.panel_zona_horaria`
  (validada contra `pg_timezone_names`; 422 si no existe) con `date_trunc(unidad, ts AT TIME ZONE zona) AT
  TIME ZONE zona` y devuelve cada bucket como instante UTC (`inicio_utc`, con `Z`); el panel solo formatea
  con `Intl`. Tests en `backend/tests/test_dashboard.py`: medianoche argentina, igual resultado con la
  sesión en UTC / Buenos Aires / Tokyo, zona inválida.

## Almacén de exportaciones

Lo que el sistema exporta por su cuenta (eventos, corte 19c) se guarda en un almacén S3-compatible,
porque el disco del backend desplegado es efímero. **Decidido el 2026-11-24:** producción usa un bucket de
Supabase Storage (1 GB en el plan Free); mudarse a otro S3 = cambiar `EXPORT_S3_ENDPOINT`, `_BUCKET`,
`_KEY` y `_SECRET`. En desarrollo y tests se usa el Storage local de Supabase (el que levanta `make up`;
API S3 en `http://127.0.0.1:54321/storage/v1/s3`, claves en `supabase status`); un S3 alternativo (SeaweedFS; MinIO ya no publica imágenes públicas) queda como perfil
opcional del compose (`--profile s3-alt`) y en CI, para probar que no hay acople a Supabase. Cliente:
`boto3` en un hilo. El disco (`ETL_EXPORT_DIR`) solo lo usa el worker local. Diseño en `docs/04` §11.4. **Implementado (corte 19c):** `etl/comun/almacen.py` (interfaz y las dos
implementaciones), `make almacen-probar`, `make s3-alt-up` (perfil `s3-alt` del compose) y el ETL
`eventos_exportar` con borrado seguro (sube, relee, compara sha256 y recién ahí borra, por ids). Las
programaciones (`etl_programaciones`, cron en UTC, ciclo con `pg_try_advisory_xact_lock`) encolan en la
misma cola de ETL.

## Eventos de producto

Lo que hace la gente en la app y conviene analizar (escanear, abrir la app…) se registra en **una tabla
genérica `eventos`** con un registro de tipos en el backend (`services/eventos.py`), no una tabla por
concepto. Un evento nuevo es una entrada en el registro, no una migración. Diseño en `docs/04` §11.2.
Los eventos llevan el id de usuario y nada más personal (sin ubicación ni texto libre).

**Implementado (corte 19b):**

- `POST /v1/eventos` recibe hasta 50 eventos `{tipo, datos, ocurrio_en_cliente?}`; todo o nada. Tipo
  desconocido o solo del backend → 400 (`evento_tipo_desconocido`); `datos` inválidos → 422
  (`evento_datos_invalidos`). Rate limit por usuario: `config.max_lotes_eventos_por_hora` (120).
- `ocurrio_en` lo pone el servidor; el reloj del celular se guarda en `datos.ocurrio_en_cliente` y no se
  usa para agrupar. Tipos iniciales: `producto.escaneado` y `app.abierta`.
- **La app** (`app/lib/data/cola_eventos.dart`) junta los eventos en memoria y los manda ~5 s después del
  primero nuevo (o al pasar a segundo plano). **Nunca estorba:** `registrar` es síncrono, el pedido es «silencioso» (no prende
  «Despertando servidor…») y, si falla por lo que sea (sin red, timeout de 10 s, 4xx/5xx), el lote se
  **descarta**, sin errores ni reintentos. No hay persistencia en disco: si el sistema mata la app, lo
  pendiente se pierde (son estadísticas).
- Retención (`config.eventos_max_filas`, 100 000): solo el valor; el aviso y la exportación son del 19c.

## Cuentas ligables (corte 21)

Diseño: `docs/superpowers/specs/2026-11-26-cuentas-ligables-design.md`; plan: `docs/04-plan-v0.2.md` parte A.

- **Cliente → backend → GoTrue.** La app obtiene un `id_token` con Google Sign-In nativo
  (`google_sign_in`, `serverClientId` = el cliente **Web**, `--dart-define=GOOGLE_WEB_CLIENT_ID`; `make apk`
  lo toma de `.env`) y se lo manda al backend, que lo reenvía a GoTrue (`grant_type=id_token`). El cliente
  nunca habla con GoTrue.
- **Endpoints** (`api/v1/auth.py`): `POST /v1/auth/google/ligar` (con la sesión anónima: GoTrue, con
  `link_identity`, conserva el `auth_id`; `usuarios.es_anonimo=false` y se guarda el email) y
  `POST /v1/auth/google/entrar` (sin sesión; si el Google es nuevo se crea un usuario con las mismas defensas
  que `/anonymous`: rate limit, `modo_acceso`, invitación, dispositivo con baja). 409 `ya_ligada` si la
  cuenta ya lo está; 409 `google_ya_ligado` si ese Google es de otra cuenta (GoTrue lo dice con 422
  `identity_already_exists`). `GET /v1/me` trae `ligada` y `sugerir_ligar` (anónima y
  `karma >= config.karma_umbral_ligar_cuenta`, 3); el email no sale nunca.
- **GoTrue** necesita `enable_manual_linking = true` y el provider Google con el cliente Web
  (`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` en `.env`; `make up` los exporta).
- **Estado `fusionada`** (`usuarios.estado`, `fusionada_en` → destino; check de coherencia): no es `baja`
  porque la baja marca el dispositivo y bloquearía altas legítimas. `current_user` y `/refresh` la
  rechazan con 403 `cuenta_fusionada`.
- **Reclamo** (`POST /v1/admin/usuarios/{id}/reclamar`, capacidad `usuario.reclamar`, solo admin,
  `services/reclamos.py`): bloquea ambas filas, suma el karma, reasigna autoría (`precios`, `locales`,
  `sugerencias_catalogo`, `avisos_catalogo`, `validaciones`; un choque de unicidad se queda con la huérfana
  y se informa) y audita (`usuario.reclamar`).
- **Nonce:** la app no manda nonce (no se pudo verificar sin el celular); si GoTrue lo exigiera hay que
  agregarlo (`skip_nonce_check` o un nonce propio en `google_signin_service.dart`).

## Alias del usuario

El alias es un atributo del **perfil** (`usuarios.alias`), no de la identidad del proveedor de auth: no
depende de cómo entró la persona (anónimo, email, Google/Apple) y sobrevive a asociar el anónimo con un
email o a vincular un OAuth (el perfil sigue siendo el mismo `usuarios.id`). Diseño y reglas en
`docs/superpowers/specs/2026-11-25-alias-editable-design.md`; plan de corte en `docs/04` §12.

- **Nace** como `anon-XXXXXX` (6 hex del `auth_id`). **Cambiarlo:** `POST /v1/me/alias`; `GET /v1/me` trae
  `puede_cambiar_alias`. Lo pueden usar los roles de `config.alias_editable_por_rol` (hoy
  `["moderador","admin"]`; para abrirlo a todos se suma `"usuario"` desde Configuración del panel, sin
  tocar código; el admin siempre puede).
- **Reglas** (`services/alias.py`): 3 a 24 caracteres, letras (con tildes), números, espacio, `.`, `_`, `-`;
  empieza y termina con letra o número; único **sin distinguir mayúsculas** entre alias vigentes (índice
  único parcial en Postgres, los `anon-%` quedan afuera); reservados: prefijo `anon-` y palabras como
  `admin` o `moderador` (también `Admin2`, `4dmin`, `A.d.m.i.n`); lista de bloqueo en
  `config.alias_bloqueados`; tope `config.alias_max_cambios_por_dia` (3, se cuenta en el historial; el
  admin no tiene tope); un usuario restringido por karma no puede. Al cambiar, el alias anterior **se
  libera**. Un admin editando desde el panel solo está sujeto a formato y unicidad.
- **Historial:** `usuarios_alias_historial` (alias anterior y nuevo, `cambiado_en` UTC, quién y origen:
  `alta | usuario | admin | sistema`), solo se agrega, llenada por un **trigger** de Postgres (nadie cambia
  el alias sin dejar rastro, tampoco `make admin-crear` ni el alta perezosa). Sin foreign keys a propósito
  (como `eventos`): el rastro sobrevive a un perfil borrado. Se ve en la ficha del usuario del panel
  (`alias_historial`).

## Historial de precios por local (corte 22)

Diseño en `docs/superpowers/specs/2026-11-26-historial-por-local-design.md`.

- **`GET /v1/productos/{ean}/locales`** (`backend/app/api/v1/productos.py`): los locales entre los que
  se puede elegir. Solo `verificado`. Con `lat` y `lng` (van juntos, si no 422): los que están dentro de
  `config.radio_precios_m`, **tengan o no precio** del producto, por distancia, con `distancia_m` y
  `ultimo_precio`/`fecha` (nulos si no hay). Sin ubicación: solo los que tienen precio, el más reciente
  primero, sin distancia. El historial de un local sale de `GET /v1/productos/{ean}/precios?local_id=`
  (ya existía; `PrecioHistorial` de la app ahora guarda `local_id`).
- **App** (`ui/historial_local_screen.dart`): botón «Ver historial por local» en la ficha, encima de
  «Cargar precio» (oculto si nadie cargó nada). Título = local (con distancia, selector si hay más de
  uno); producto debajo; tabs en píldora **Gráfico** (izquierda, el que abre; `ui/grafico_precios.dart`, `CustomPainter` propio,
  eje lineal, sin librerías nuevas) y **Mapa** (derecha; `ui/mapa_local.dart`, carteles «Vos» y «Local»); los tabs miden 240, como el mapa de la ficha, y no se cambian deslizando (el gesto es del mapa).
  Debajo, «Historial de precios»: filas compactas con la variación contra el precio anterior como
  flecha + % (`domain/historial.dart`: `conVariacion`, `etiquetaVariacion`, `rangoEje`); con ≥ 640 px de
  alto la cabecera queda fija y solo la lista se desplaza. Tocar (o arrastrar sobre) un punto del gráfico
  muestra su precio y día. El ícono de escanear es `IconoCodigoBarras` (`ui/icono_codigo_barras.dart`, dibujado: Material no trae uno; el EAN siempre es un código de barras). La distancia al local va en el cuerpo («A 120 m de vos»), no en el título, para que el nombre del local tenga lugar; las filas pares van sombreadas para leer cada porcentaje. Sin GPS se muestran los locales con precio, sin distancia ni «Vos».
  Un local sin precios del producto: mensaje, «Ir al inicio» y «Escanear».
- **«Escanear otro»** quedó en `ui/escanear_otro.dart`, compartido por la ficha (reemplaza la ficha) y el
  historial (vuelve al inicio y apila la ficha nueva).
- **La ficha** ya no tiene la sección «Historial de precios» que mezclaba todos los locales.
- El gráfico acepta `MarcaGrafico` (líneas verticales con texto): las usará el corte 23 (hitos).

## Flujo de carga y «Recientes» (corte 20)

Cierra el release 0.1.x. Diseño en `docs/superpowers/specs/2026-11-25-flujo-carga-recientes-design.md`;
principios en `docs/10-roadmap.md` (la app es una guía, no un tracker financiero).

- **Volver a la ficha tras cargar un precio:** `PriceScreen` ya no tiene pantalla de éxito; al guardar
  hace `pop` con el `PrecioCargado` y la ficha (`ProductScreen`) avisa («Precio cargado · karma N») y
  recarga lista, mapa e historial. El alta de producto (`SugerirScreen`) ya volvía a la ficha.
- **«Escanear otro»** (botón de la barra de la ficha): abre el escáner y, si lee un código, **reemplaza**
  la ficha (`pushReplacement`): un solo «atrás» lleva al inicio por más productos que se escaneen. El
  inicio se entera de cualquier vuelta con un `RouteObserver` (`routeObserver` en `ui/recientes.dart`),
  no con el `await` del `push`.
- **«Recientes»** (`app/lib/data/recientes.dart`, `ui/recientes.dart`): hasta **`config.recientes_max`** (10 por defecto; la app lo lee de `/v1/config` y lo recuerda en el celular) consultas, en una lista con scroll propio y una tarjeta por producto, bajo el
  campo de EAN, sin repetir EAN (reconsultar lo sube al tope). Se guardan **solo en el celular**
  (`shared_preferences`, clave `recientes_v1`): EAN, instante y una **foto** (nombre, detalle y el
  `PrecioVigente` visto: precio, local, distancia, fecha). Nunca falla ni demora: leer/escribir
  atrapan todo y las escrituras van en fila; sin red se ve la foto, con red `RecientesService.refrescar`
  la actualiza aparte (timeout 10 s, cada 5 min como mucho por entrada, sin mover su lugar).
  Tocar uno abre la ficha sin anotar el evento `producto.escaneado` (no fue un escaneo).
- **Qué precio se muestra:** el del local **más cercano** (no el más barato) dentro de
  `config.radio_precios_m`. Si no hay, se pide `precios/vigentes?referencia=true` (radio
  `config.radio_referencia_km`, **300** por defecto) y se muestra **marcado «Referencia» y con su
  distancia** («a 120 km»), nunca como precio de la zona. Sin ubicación no hay distancia: también va como
  referencia («sin ubicación»). Sin ningún precio: «Sin precios cargados · sé el primero en cargarlo».
- **Backend `GET /v1/productos/{ean}/precios/vigentes`:** el tope de `radio_m` ya no es un `100_000`
  fijo: es `max(radio_precios_m, radio_referencia_km × 1000)`; pasarse da 422. `referencia=true` pide
  justo ese radio (la app no necesita conocer el número) y exige `lat`/`lng`.
- **«Sé el primero en cargarlo»:** si el historial del producto está vacío (ningún local), el botón de
  la ficha lo dice y va debajo del nombre. `POST /v1/precios` suma `config.karma_primer_precio` (**5**) al
  primer precio de un producto, **una sola vez** (lock por producto dentro de la transacción) y
  devuelve `primer_precio: true`; la app avisa «¡Fuiste el primero en cargarlo!». Repetir un precio
  propio no suma ni bonus.

## Versionado de releases

El esquema de versiones cambió: la 0.0.1 fue una compilación vieja y **ya no está vigente**; el próximo
release fue el **0.1.x** (cerrado el 2026-11-25; plan en `docs/04-plan-v0.1.md`). Donde estos docs dicen «v0.0.1» o «v0.0.2» se refieren a los **planes** históricos
(alcance de entonces), no a versiones de release. El resto de releases (0.2.x en adelante) está en `docs/10-roadmap.md`, con un plan por release
(`docs/04-plan-v0.2.md` …).

La serie 0.1 está en `app/pubspec.yaml` (`version: 0.1.0+1`); `make apk` arma 0.1.0, 0.1.1… (Doc 4, «Versión del APK»).

## Testing

- Backend: pytest. Integración contra el Postgres local real (el del CLI), no mocks.
- v0.0.1 mínimo: lógica de karma + smoke de endpoints.
- Flutter: unit + widget. Integración, más adelante.

## CI

- GitHub Actions. El YAML solo llama a targets del Makefile (lint + test en cada PR).
  Así migrar a otra plataforma (ej. GitLab) = reescribir solo un YAML chico; los
  comandos reales no se tocan.
- Deploy manual al principio.

## Deploy

- Backend: imagen Docker. Destinos de hobby: Fly.io / Render / Railway. La misma
  imagen se mueve a VPS propia más adelante.
- App: Android. Build local; distribución a testers vía APK directo (grupo
  cerrado). iOS más adelante (requiere Apple Developer, USD 99/año).

## Convenciones

- API versionada: prefijo `/v1`.
- Secrets: `.env` local (nunca commitear), secrets de plataforma en prod. Hay
  `.env.example`.
- Logs: structured logging simple. Observability, más adelante.
- Nada acoplado a Supabase por nombre en el código propio.
