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

- `usuarios`: id (uuid, pk), auth_id (ref al usuario de Supabase Auth), alias,
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
API S3 en `http://127.0.0.1:54321/storage/v1/s3`, claves en `supabase status`); MinIO queda como perfil
opcional del compose (`--profile s3-alt`) y en CI, para probar que no hay acople a Supabase. Cliente:
`boto3` en un hilo. El disco (`ETL_EXPORT_DIR`) solo lo usa el worker local. Diseño en `docs/04` §11.4.

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

## Versionado de releases

El esquema de versiones cambió: la 0.0.1 fue una compilación vieja y **ya no está vigente**; el próximo
release es **0.1.x**. Donde estos docs dicen «v0.0.1» o «v0.0.2» se refieren a los **planes** históricos
(alcance de entonces), no a versiones de release. La validación colaborativa llega, probablemente, en
0.2.x o posterior.

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
