# Plan v0.0.2

Estado: **propuesta para revisar**. Parte de v0.0.1 cerrada y probada en un
celular real (escanear, cargar precio, karma, historial). Ante una duda de
comportamiento gana el Doc 1; ante una duda técnica, el Doc 2. Este plan
**cambia una regla del Doc 1** (alta de locales, ver §2); al aprobarlo hay que
actualizar ese doc y la sección de alcance de `CLAUDE.md`.

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
| 8 | Frescura visible + precio vigente por local | — | chico |
| 9 | Anti-spam (invitaciones, rate limit, límites por usuario) | 5 | medio |
| 10 | Preparar release: firma del APK y guía de deploy | — | chico |

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

## 2. Alta de local por cualquier usuario (corte 5)

**Cambia el Doc 1** («por ahora solo el admin crea locales»). Decisión del
dueño del proyecto: se permite a un usuario anónimo crear el local donde está,
para poder seguir probando y cargando.

Diseño:

- `locales.verificado boolean not null default false`. El local creado por un
  usuario nace **sin verificar** pero usable, así no se frena la carga. El admin lo
  verifica, corrige o fusiona con un duplicado.
- `POST /v1/locales` con nombre y la ubicación **actual** (lat/lng). La
  ubicación sale del GPS, no se tipea: es lo que da sentido al geofence.
- **Anti-duplicados:** si ya hay un local a menos de ~50 m, el backend lo
  devuelve como sugerencia y la app pregunta «¿es este?» en vez de crear otro.
- **Límite por usuario:** pocos locales nuevos por día (valor en `config`).
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

## 4. Catálogo real: ETL de Open Food Facts (corte 7)

- Pipeline en `etl/` (Python, aparte del backend), con target `make etl`.
- **Fuente:** el volcado completo de Open Food Facts (no la API producto por
  producto). Es un archivo de varios GB: se baja a `etl/data/` (ya ignorado por
  git) y se procesa en streaming. **La descarga grande requiere tu OK** cuando
  llegue el momento.
- **Pasos:** filtrar productos de Argentina → validar el EAN (largo y dígito
  verificador) → normalizar `quantity` a `tamano_valor` + `tamano_unidad`
  (`"900 ml"`, `"1,5 L"`, `"500g"`; los multipack se tratan aparte o se
  descartan) → *upsert* por EAN con `origen = 'off'`.
- **Idempotente y sin pisar al admin:** no sobrescribe filas con
  `origen = 'manual'`. Se puede correr de nuevo sin duplicar.
- Imagen: URL de OFF, no se guarda el archivo (Doc 2).
- Tendrá tests sobre la normalización (es donde se ensucian los datos) y un
  reporte de cuántos productos se cargaron y cuántos se descartaron y por qué.
- **Otras fuentes a investigar** (cada una sería su propio ETL): los datos
  abiertos de precios del Estado argentino (SEPA / «Precios Claros») traen
  productos con EAN y precios por comercio; hay que revisar formato, licencia y
  frecuencia antes de decidir. También aportes manuales del admin.
- A futuro se podría ofrecer «alta mínima de producto» desde la app para EAN que
  ningún ETL cubra; queda fuera de v0.0.2.

## 5. Frescura y precio vigente (corte 8)

- Nuevo `GET /v1/productos/{ean}/precios/vigentes`: **el último precio de cada
  local**, con antigüedad en días y un estado `fresco` / `viejo` / `vencido`.
  El backend lo calcula con los umbrales de `config` (`umbral_verde_dias`,
  `umbral_amarillo_dias`, `ventana_frescura_dias`): es lógica de negocio.
- La ficha muestra primero los vigentes por local, con color (verde / amarillo /
  rojo) y la fecha siempre visible; el historial completo queda debajo.
- Sin estimación por IPC en esta versión (Doc 1 la prevé, marcada como
  estimación; se deja para más adelante).

## 6. Anti-spam sobre `/v1/auth/anonymous` (corte 9)

El riesgo: el endpoint es público por diseño (la sesión anónima es el onboarding
sin fricción) y cada usuario nuevo puede cargar precios y ganar karma. Capas, de
la más barata a la más pesada:

1. **Aplicar `modo_acceso`** (ya existe en `config`, hoy en `solo_invitacion`,
   pero nada lo lee). Con ese modo, crear una sesión anónima exige un **código de
   invitación**. Es la defensa más fuerte para un grupo cerrado de ~50 personas
   y está en el Doc 1. Códigos por persona (tabla `invitaciones`: código, usos
   máximos, usos, vencimiento), emitidos por el admin; así se puede revocar uno
   sin afectar a los demás. La app pide el código solo en el primer arranque.
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
| Backend FastAPI | Fly.io, Render o Railway (hay que elegir) | Los tres dan HTTPS automático en su subdominio, **sin comprar dominio**. Costo bajo pero no necesariamente cero; el plan gratis de algunos duerme el servicio (primer request lento). Verificar precios vigentes. |
| App | APK firmado | Se instala a mano. |

Variables del backend en producción (secrets de la plataforma, nunca en git):
`DATABASE_URL` (cadena de Supabase; ojo: la conexión directa suele ser solo IPv6
y el *pooler* en modo transacción rompe las *prepared statements* de `asyncpg`,
así que conviene el *session pooler* o ajustar el cliente: probarlo antes),
`AUTH_URL` (`https://<proyecto>.supabase.co/auth/v1`), `AUTH_API_KEY` (la clave
anon), `JWKS_URL`. Las migraciones se aplican a mano a la base remota; **no** se
corre el seed de desarrollo, solo la config inicial y los datos reales.

### ¿Hace falta un dominio?

No para probar: alcanza el subdominio HTTPS del host. Pero **conviene comprarlo
antes de repartir el APK**, por una razón práctica: la URL de la API queda
grabada en el APK. Con un dominio propio (`api.tudominio.com`) se puede cambiar
de host (de Render a Fly, o a una VPS) **sin recompilar ni reinstalar nada**.
Además da una imagen más profesional y permite poner Cloudflare delante (capa
extra anti-spam). Costo orientativo: unos USD 10-15 al año por un `.com`; un
`.com.ar` se gestiona en NIC Argentina y pide CUIT/CUIL (verificar).

### Qué tendrías que hacer vos

- Crear la cuenta y el proyecto de Supabase.
- Crear la cuenta en el host elegido (puede requerir tarjeta).
- (Opcional) Comprar el dominio.
- Generar la keystore con tu propia contraseña.

Yo preparo el resto (Dockerfile listo para prod, guía paso a paso en `docs/`,
`make` targets, configuración del `build.gradle.kts`) sin tocar tus cuentas ni
credenciales.

## Decisiones que necesito de vos

1. **Alta de local por cualquier usuario, sin verificar** (§2): ¿confirmás, con
   el anti-duplicados y el límite diario?
2. **Invitaciones por persona** (§6) vs. un único código compartido: recomiendo
   por persona.
3. **Host del backend** (§7): Fly.io, Render o Railway. Recomiendo decidirlo con
   los precios vigentes a mano cuando lleguemos al corte 10.
4. **Dominio:** ¿lo comprás antes del primer reparto del APK?
5. **`applicationId`:** ¿queda `ar.almacenero.almacenero`?

## Documentación a actualizar al ejecutar el plan

- Doc 1: alta de locales por usuarios; invitaciones; roles.
- `CLAUDE.md`: alcance de v0.0.2 (hoy solo describe v0.0.1).
- `docs/03-problemas-soluciones.md`: lo que vaya apareciendo en cada corte
  (como hasta ahora).
