# Doc 3 — Problemas, soluciones y decisiones

Registro de lo que falló mientras se armó el proyecto, cómo se resolvió y por qué se
tomaron ciertas decisiones. Sirve para **recrear el entorno en otra máquina sin
tropezar con lo mismo**. No es fuente de verdad del producto (Doc 1) ni de la
arquitectura (Doc 2): si algo acá los contradice, ganan ellos.

Cuando aparezca un problema nuevo, agregalo a la sección que corresponda con el
formato **Síntoma → Causa → Solución**.

- [Armar el entorno desde cero](#armar-el-entorno-desde-cero)
- [Entorno Android y Flutter](#entorno-android-y-flutter)
- [Proyecto Flutter](#proyecto-flutter)
- [Backend, auth y Supabase](#backend-auth-y-supabase)
- [CI](#ci)
- [Git y GitHub](#git-y-github)
- [Probar en emulador y en celular](#probar-en-emulador-y-en-celular)
- [Decisiones de diseño](#decisiones-de-diseño)
- [Deuda conocida](#deuda-conocida)

---

## Armar el entorno desde cero

Pensado para macOS con Apple Silicon y Homebrew. Cada paso tiene su explicación más
abajo. Ya no hace falta Android Studio.

```bash
# 1. Herramientas base
brew install gh openjdk@17 supabase/tap/supabase   # + Docker Desktop, Flutter y psql
brew install --cask android-commandlinetools

# 2. Variables (agregalas a ~/.zshrc)
export JAVA_HOME=/opt/homebrew/opt/openjdk@17
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

# 3. SDK de Android (aceptá las licencias cuando las pida)
yes | sdkmanager --licenses
sdkmanager "platform-tools" "emulator" "platforms;android-35" "platforms;android-36" \
  "build-tools;35.0.0" "build-tools;28.0.3" "ndk;28.2.13676358" \
  "system-images;android-35;google_apis;arm64-v8a"

# 4. Flutter apuntando a ese SDK y a ese JDK
flutter config --jdk-dir "$JAVA_HOME" --android-sdk "$ANDROID_HOME"
flutter doctor            # Xcode en rojo es esperable: iOS está fuera de alcance

# 5. Emulador
echo no | avdmanager create avd -n almacenero_pixel -d pixel_8 \
  -k "system-images;android-35;google_apis;arm64-v8a"
emulator -avd almacenero_pixel -no-snapshot

# 6. Proyecto
gh auth login && gh repo clone <usuario>/almacenero && cd almacenero
make up && make test
```

Los números de versión (Flutter 3.50, SDK 36, build-tools 28.0.3, NDK 28.2) son los
que pidió el Flutter usado al armar esto. Si `flutter doctor` o Gradle piden otros,
instalá esos.

---

## Entorno Android y Flutter

### Flutter muy viejo (3.3.7)
- **Síntoma:** `flutter doctor` mostraba 3.3.7 (2022). Paquetes como `mobile_scanner`
  exigen un Flutter bastante más nuevo.
- **Solución:** `flutter upgrade`.
- **Tropiezo:** se negó con *"Your flutter checkout has local changes"*. El único
  cambio era `tool_state`, un archivo de estado de la propia herramienta (sin código
  del usuario), así que `flutter upgrade --force` es seguro. Antes de forzar, mirá
  `git status` dentro de la carpeta de Flutter (`flutter --version` muestra dónde).

### No hay Android SDK ni emulador
- **Síntoma:** `Unable to locate Android SDK`.
- **Solución:** sin Android Studio, por línea de comandos. `brew install --cask
  android-commandlinetools` deja el SDK en
  `/opt/homebrew/share/android-commandlinetools`, y `flutter config --android-sdk`
  apunta ahí.

### `sdkmanager` no corre: pide Java 17+
- **Síntoma:** el Java activo era el 8 (instalado con sdkman).
- **Solución:** `brew install openjdk@17` y usarlo con `JAVA_HOME` solo para estos
  comandos, sin tocar el Java global. Para que Gradle compile con ese JDK:
  `flutter config --jdk-dir /opt/homebrew/opt/openjdk@17`.

### Flutter exige componentes que no se instalaron
- **Síntoma:** `flutter doctor`: *"Flutter requires Android SDK 36 and the Android
  BuildTools 28.0.3"*.
- **Solución:** además del SDK 35 de la imagen, instalar `platforms;android-36` y
  `build-tools;28.0.3`.

### Las descargas grandes se cortan por timeout
- **Síntoma:** `sdkmanager` o Gradle fallaban con *"Operation timed out"* a mitad de
  descarga (imagen de sistema de ~1.5 GB, distribución de Gradle, NDK). Una vez la
  Mac hibernó y el proceso quedó colgado sin avanzar (el tamaño de la carpeta no
  crecía).
- **Causa:** red intermitente y, en el caso de la hibernación, la conexión cortada.
- **Solución:** reintentar en un bucle (lo ya descargado se conserva en gran parte) y
  **evitar que la Mac hiberne** mientras tanto. Si el proceso no crece, matarlo y
  relanzarlo.
  ```bash
  for i in 1 2 3 4 5 6; do sdkmanager --install "<paquete>" && break; done
  ```

### Gradle se cuelga bajando el NDK
- **Síntoma:** el build se quedaba en *"Downloading android-ndk-r28c…"* (27%).
- **Solución:** instalarlo antes con `sdkmanager "ndk;28.2.13676358"` (reintentable) y
  recién después compilar. El primer build de la app lleva varios minutos por esto.

### `avdmanager` imprime un error pero el emulador se crea
- **Síntoma:** `Error: Could not load devices from …/devices.xml` al crear el AVD.
- **Causa:** es un aviso; el AVD se crea igual.
- **Solución:** ignorarlo y confirmar con `avdmanager list avd` o `flutter emulators`.

### Con la máquina cargada, todo anda lento
- **Síntoma:** emulador + Docker + Gradle a la vez: `adb` tarda, y `adb shell input
  text` **pierde caracteres**.
- **Solución:** `cd app/android && ./gradlew --stop` para liberar los daemons de
  Gradle. Para tipear en el emulador, mandar una tecla por dígito
  (`adb shell input keyevent KEYCODE_7`) en vez de `input text`.

---

## Proyecto Flutter

### `android/` generado por el Flutter viejo no compila
- **Síntoma:** *"You are applying Flutter's app_plugin_loader Gradle plugin
  imperatively … not possible anymore"*.
- **Causa:** el proyecto se creó con Flutter 3.3.7 (scripts Gradle de estilo viejo) y
  después se actualizó Flutter.
- **Solución:** como `android/` no tenía cambios propios, se borró y se regeneró:
  ```bash
  cd app && rm -rf android
  flutter create --platforms=android --org ar.almacenero --project-name almacenero .
  ```
  (Reaplicar después `INTERNET` y el cleartext de debug; ver más abajo.) Moraleja:
  **actualizá Flutter antes de crear el proyecto**, no después.

### El `pubspec.yaml` seguía con Dart 2
- **Síntoma:** `sdk: '>=2.18.4 <3.0.0'` no resuelve con el Dart 3.14 del Flutter nuevo.
- **Solución:** `sdk: ^3.14.0` y subir `cupertino_icons` y `flutter_lints`.

### `package:flutter/material.dart` está deprecado
- **Síntoma:** `flutter analyze` marca `deprecated_member_use` (y `make lint` falla).
- **Solución:** `flutter pub add material_ui` y usar `package:material_ui/material_ui.dart`.
  **No mezclar** ambos imports en un mismo test: los tests de widgets fallaron
  hasta unificarlos.

### Parámetros nombrados privados
- Dart 3.12+ permite `required this._api` (el parámetro nombrado queda `api:`). Es lo
  que sugiere el lint `prefer_initializing_formals`, y se usa en los repositorios.

### Bug: `setState(() => _x = unFuture())`
- **Síntoma:** al tocar «Reintentar» → *"setState() callback argument returned a
  Future"*. Lo atajó un widget test; en el emulador habría crasheado.
- **Solución:** usar cuerpo con llaves: `setState(() { _x = unFuture(); });`.

### El backend serializa `Decimal` como string
- **Síntoma:** `tamano_valor` llega como `"900"`, no como número.
- **Solución:** parsear con `num.parse(json['tamano_valor'].toString())`
  (`Producto.fromJson`).

---

## Backend, auth y Supabase

### «Token inválido» con un token real del auth local
- **Síntoma:** el token de `/auth/v1/signup` siempre daba 401 en el backend.
- **Causa:** el Supabase CLI 3.x firma los JWT con **ES256** (clave asimétrica,
  verificable por JWKS) y el backend solo validaba HS256 con el secreto compartido.
  Los tests no lo detectaron porque firmaban sus propios tokens HS256.
- **Diagnóstico:** decodificar el header del token (`{"alg":"ES256","kid":…}`).
- **Solución:** `app/auth.py` mira el `alg`: ES256/RS256 se validan contra
  `JWKS_URL` (con caché); HS256 con `JWT_SECRET`. Requiere `PyJWT[crypto]`.
- **Lección:** al menos un test de auth debe usar el tipo de token que da el
  proveedor real (hay uno con ES256 y otro de punta a punta a mano).

### El cliente no puede pedir la sesión anónima directo al auth
- **Decisión:** la regla del repo es que Flutter habla solo con el backend. La sesión
  anónima necesita llamar a GoTrue, así que el backend la **proxea**:
  `POST /v1/auth/anonymous` y `/v1/auth/refresh`. La app nunca conoce la URL del
  proveedor.
- **Requiere** `AUTH_URL` y `AUTH_API_KEY` (la `ANON_KEY` de `supabase status`).

### `AUTH_API_KEY` quedaba vacía en `.env`
- **Síntoma:** `/v1/auth/anonymous` → 503 *"auth no configurada"*.
- **Causa 1:** dentro de `make`, `supabase status -o env` imprimió JSON y el `sed`
  no encontró `ANON_KEY`. **Solución:** pedir `-o json` y parsearlo con `python3`.
- **Causa 2:** un `.env` creado antes no tenía la línea `AUTH_API_KEY`, y el `sed`
  solo reemplazaba líneas existentes. **Solución:** quitar la línea (si está) y
  agregarla.
- `make up` ya lo hace solo. Si falla: `make up` de nuevo, o completarla a mano.

### El backend en Docker no ve `127.0.0.1`
- **Solución:** en `docker-compose.yml`, `DATABASE_URL`, `AUTH_URL` y `JWKS_URL`
  apuntan a `host.docker.internal`; en local (fuera de Docker) valen los defaults con
  `127.0.0.1`.

### Probar a mano con Swagger (`/docs`)
1. Pedir un token anónimo:
   ```bash
   curl -s -X POST http://localhost:8000/v1/auth/anonymous
   ```
2. Botón *Authorize* en `/docs` con el `access_token`. Los tokens vencen (1 h):
   pedí otro si vuelve el 401.

### Los tests contra Postgres necesitan el stack levantado
- `make test` corre pytest contra el Postgres real del Supabase CLI, **con el seed
  aplicado** (`supabase start` lo carga). Sin Docker, esos tests no corren.

### `ruff` se queja de `Depends()` en los defaults (B008)
- Es el idioma normal de FastAPI. Se ignora `B008` en `backend/pyproject.toml`.

### Confusión entre ids en las respuestas
- `/v1/me` devuelve el id del **usuario**; `POST /v1/precios` devuelve el id del
  **precio** creado (más el karma resultante). No son el mismo id.

---

## CI

### `make up` falla en GitHub Actions
- **Síntoma:** `failed to parse config: 'db.migrations' has invalid keys: enabled`.
- **Causa:** `supabase/setup-cli` instalaba una versión distinta (`latest`) del CLI
  que la de desarrollo, y esa rechazaba una clave del `config.toml`.
- **Solución:** fijar la versión en `.github/workflows/ci.yml` (`version: 3.1.0`),
  igual que en local. **Cuando subas el CLI local, subí también esa versión.**
- Si el CI de `main` falla desde el principio, nadie se entera hasta mirar la pestaña
  Actions: miralo con el primer push.

---

## Git y GitHub

### `gh` no estaba instalado ni logueado con la cuenta correcta
- **Solución:** `brew install gh` y `gh auth login` (navegador, HTTPS). Antes de
  autorizar, verificá en el navegador **con qué cuenta** estás logueado; se puede
  tener otra cuenta de GitHub abierta. Confirmar con `gh auth status`.
- Si Git sigue usando credenciales de otra cuenta, borrar la entrada de `github.com`
  del llavero de macOS o correr `gh auth setup-git`.

### El commit salió con un email que no era el de la cuenta
- **Causa:** el `user.email` de Git en esa máquina era el de otro contexto (trabajo).
- **Solución (solo en este repo):**
  ```bash
  git config user.email "<id>+<usuario>@users.noreply.github.com"
  git config user.name "<usuario>"
  git commit --amend --reset-author --no-edit   # solo si todavía no se pusheó
  ```
  El email *noreply* atribuye el commit a la cuenta sin exponer un email real
  (`gh api user --jq .id` da el id).

### El repo es público
- Por eso `.env` está ignorado y `.env.example` solo trae valores de desarrollo
  local (el secreto JWT demo es el mismo para todos los Supabase locales). No
  documentes acá emails, tokens ni datos personales.

---

## Probar en emulador y en celular

### Emulador
- **La app abre y se queda en el splash de Flutter:** en debug, la primera vez
  tarda 20–30 s en renderizar. No es un crash; confirmalo con `adb logcat`.
- **`am start` → *Activity class … does not exist*** justo después de bootear el
  emulador: es transitorio, reintentar.
- **El escáner muestra una escena pixelada:** es la cámara virtual del emulador.
  Sirve para comprobar que la cámara abre y pide permiso, pero **no lee códigos de
  barras**. Para escanear de verdad, un celular.
- **Desde el emulador, el backend es `http://10.0.2.2:8000`** (es el valor por
  defecto de `API_URL`).
- **«… isn't responding» (ANR) y todo lentísimo:** presión de memoria de la Mac
  (swap casi lleno, Docker al 190 % de CPU, daemons de Gradle vivos). Solución:
  `./gradlew --stop`, cerrar lo que no se use, reiniciar el emulador en frío
  (`adb emu kill` y relanzar con `-no-snapshot -no-audio -no-boot-anim`).
- **`monkey -p <paquete> 1` no abre la app** (no hay `MainActivity` con ese
  nombre de paquete: el `applicationId` es `ar.almacenero.almacenero`). Tocar el
  ícono de Flutter en el launcher y esperar ~40 s en el primer arranque debug.
- **El historial de un producto muestra precios «de más» en el entorno local:** son
  los que cargan los tests del backend (usan la misma base). No es un bug.
- **Otra vez «… isn't responding» con el stack completo de Supabase arriba:** el
  Docker de la Mac (8 GB) + el emulador (5-6 GB) agotan la memoria. Dos remedios
  que sí funcionan: (1) parar los contenedores de Supabase que este proyecto no usa
  (`studio`, `analytics`, `vector`, `edge_runtime`, `pg_meta`, `realtime`,
  `inbucket`; el backend solo necesita `db`, `auth` y `kong`) con
  `docker stop supabase_<nombre>_almacenero`; (2) arrancar el emulador con menos
  RAM: `emulator -avd almacenero_pixel -no-snapshot -no-audio -no-boot-anim -memory 3072`.
  `supabase start -x <contenedores>` permite no levantarlos desde el principio.
- **Al pedir ubicación, Google Play Services también se cuelga** («Google Play
  services isn't responding») y puede mostrar un aviso de «precisión de
  ubicación». Con poca RAM el flujo de GPS no se completa en el emulador: usar
  el celular, o darle más memoria al emulador si la máquina lo permite. El
  backend de locales se puede verificar igual con `curl` (ver los tests).
- **Ubicación en el emulador:** `adb emu geo fix <longitud> <latitud>` (¡primero
  longitud!) fija el GPS virtual. Sirve para probar «locales cerca» y el alta de un
  local sin moverte.
- **`adb shell input text` pierde caracteres con la máquina cargada:** para teclear
  números usar `input keyevent` por dígito, todo en un solo `adb shell`.

### Celular real
- **`10.0.2.2` no existe en un celular.** `make apk` compila un APK debug (arm64)
  apuntando a la IP de la máquina en la red (`LAN_IP=… make apk` para forzarla).
- **HTTP sin TLS:** solo funciona en el build *debug* (el `AndroidManifest` de
  `debug/` habilita `usesCleartextTraffic`). Un build release necesita backend con
  HTTPS.
- **Para que conecte:** mismo Wi-Fi que la máquina, backend arriba (`make up`), y
  ojo con tres cosas: la IP cambia (recompilar), el firewall de macOS puede bloquear
  a Docker, y algunas redes (invitados) aíslan los dispositivos entre sí.
- **Instalar:** `adb install -r app-debug.apk` con USB, o pasar el archivo y permitir
  «instalar apps desconocidas» (Play Protect avisa; «Instalar de todos modos»).
- **Qué ves al escanear un código que no está en el seed:** *«Este producto todavía
  no está en el catálogo»* con el EAN leído, lo que ya confirma que la cámara lo
  reconoció. Sin backend alcanzable, muestra el EAN con *«No pudimos conectar»*.

---

## Decisiones de diseño

- **Auth anónima vía backend** (arriba): mantiene la regla «el cliente habla solo con
  el backend» y deja el proveedor de auth intercambiable.
- **`usuarios.auth_id` sin foreign key** a `auth.users`: el esquema no depende del
  schema `auth` de Supabase y queda portable a cualquier Postgres.
- **Karma protegido en Postgres, escrito por el backend:** un trigger rechaza
  cambiar `usuarios.karma` salvo que la transacción haga
  `select set_config('app.karma_write', 'on', true)`. Integridad en la base
  (Doc 2), regla de negocio en el backend.
- **Variables sin nombre de proveedor:** `JWT_SECRET`, `JWKS_URL`, `AUTH_URL`,
  `DATABASE_URL`. Nada acoplado a Supabase por nombre.
- **Sesión en almacenamiento cifrado** (`flutter_secure_storage`): el refresh token
  es sensible. La sesión se renueva sola y, ante un 401, se reintenta una vez.
- **Un solo `AuthedApi`** para las llamadas autenticadas, así la lógica de refresh no
  se repite en cada repositorio.
- **Entrada manual de EAN junto al escáner:** es el plan B si falla la cámara o el
  permiso, y permite probar sin celular.
- **EAN: solo se valida largo (8–14 dígitos)**, no el dígito verificador.
- **El precio viaja como string, nunca como número:** la app lo normaliza
  (`parsearPrecio`: acepta coma o punto, hasta 2 decimales, rechaza separador de
  miles y 0) y lo manda como `"1234.50"`; el backend lo recibe como `Decimal`. Evita
  errores de punto flotante.
- **Respuesta de `POST /v1/precios`: `precio_id` y `karma`** (antes `id`), para no
  confundirlo con el id de usuario de `/v1/me`.
- **`AppDeps`:** la UI recibe un conjunto de funciones (`loadMe`, `loadProducto`,
  `loadLocales`, `cargarPrecio`) en vez de repositorios; los widget tests usan un
  backend falso sin red.
- **Al volver de cargar un precio**, el inicio refresca el karma y vacía el campo de
  EAN, listo para el siguiente producto.
- **v0.0.1 usa el primer local de `/v1/locales`** (el del admin).
- **Historial de precios en la ficha del producto** (no en una pantalla aparte):
  se ve junto al botón «Cargar precio» y se recarga al volver de cargar uno. Si el
  historial falla, la ficha sigue visible y ofrece reintentar.
- **`GET /v1/productos/{ean}/precios` devuelve `local_nombre` y `fecha` ISO 8601**
  (antes `fecha` era texto de Postgres y no traía el nombre del local). La app
  muestra la fecha con antigüedad («15/11/2026 (hace 3 días)»), porque la
  frescura del precio importa (Doc 1).
- **Rol protegido en Postgres, igual que el karma:** `usuarios.rol` solo cambia
  dentro de una transacción que haga `select set_config('app.rol_write', 'on', true)`.
  La API no tiene ningún camino para escribirlo; un admin se crea con
  `make admin ALIAS=<alias>`.
- **Permisos por capacidad, no por rol:** los endpoints piden `puede(usuario,
  "local.verificar")` (módulo `services/permisos.py`). Hoy el mapa rol → capacidades
  es un diccionario; migrar a tablas cambia ese módulo y no los endpoints (plan
  v0.0.2, §1).
- **Alta de local abierta = interruptor de prueba** (`config.alta_locales_abierta`),
  no un cambio al Doc 1. El local nace `verificado = false`.
- **Anti-duplicados sin bloquear por distancia:** hay locales contiguos legítimos.
  Solo se rechaza (409) nombre casi idéntico (`pg_trgm`, similitud ≥ 0,8) a ≤ 50 m.
  Los umbrales están en `config`.
- **Valores por defecto en código** (`services/config.py`): si falta una clave en la
  base, el backend usa el default (seguro: el alta de locales abierta es `false`).
- **Tests de locales con coordenadas al azar en el Atlántico Sur** y nombres
  `test-…`, que se borran al terminar: no ensucian los locales reales ni
  «locales cerca».
- **Mapa con `flutter_map` + OpenStreetMap:** sin clave de API ni cuenta. Las
  teselas públicas de OSM no son para uso masivo (`flutter_map` lo avisa en la
  consola en debug); sirve para el grupo cerrado y habrá que cambiar de proveedor
  antes de abrir la app. El `userAgentPackageName` identifica a la app ante OSM.
- **El mapa va fuera del scroll de la ficha** (arriba), y debajo una lista que sí se
  desplaza: un mapa dentro de un `ListView` se pelea con el gesto de scroll.
- **Precio vigente = el último de cada local** (`distinct on (local_id)`); la
  frescura (verde/amarillo/rojo) y `vencido` los calcula el backend con los
  umbrales de `config`, no la app.
- **Tests con `flutter_map`:** los carteles se buscan por `ValueKey`, y al elegir un
  local el mapa se centra en él, así que los demás carteles pueden quedar fuera de
  cuadro (el mapa no los construye). La lista es perezosa: en el test hay que
  agrandar la pantalla para que construya todas las filas.
- **Se mergean PRs apilados:** al mergear el primero, GitHub reapunta el siguiente a
  `main` solo.

---

## Deuda conocida

- `/v1/auth/anonymous` **no tiene rate limiting**: cualquiera puede crear usuarios en
  bucle (ver anti-spam en el Doc 1).
- El segundo EAN del `seed.sql` (`7791234567890`) **no tiene dígito verificador
  válido**. Hoy no importa porque solo se valida el largo; corregilo si se agrega
  validación de checksum.
- El **geofence** de carga de precios (`config.geofence_metros`) está modelado pero
  no se aplica todavía.
- El escaneo real de un código se probó en un celular, pero no hay tests
  automáticos de la cámara.
- Para distribuir a testers falta: backend desplegado con HTTPS y un build release
  firmado.

---

## ETL del catálogo (corte 7)

### El volcado completo de OFF pesa 13,6 GB… en JSONL
- **Síntoma:** el plan hablaba de «varios GB» para el volcado de Open Food Facts.
- **Causa:** el JSONL (`openfoodfacts-products.jsonl.gz`) pesa 13,6 GB; el MongoDB dump,
  16,6 GB. Pero el **CSV** (`en.openfoodfacts.org.products.csv.gz`) pesa 1,5 GB y trae
  las columnas que usamos.
- **Solución:** el ETL lee el CSV (tabulado) en streaming. Se mide con
  `curl -sIL <url> | grep -i content-length` antes de bajar nada. `make
  etl-off-muestra` baja solo los primeros ~30 MB (descarga por rango).

### Un `.csv.gz` truncado (la muestra) no debe romper el ETL
- **Síntoma:** `EOFError: Compressed file ended before the end-of-stream marker`.
- **Solución:** el lector de filas lo atrapa y termina; la última fila cortada se
  descarta por tener menos columnas que la cabecera.

### EAN-8 y UPC-A en el volcado de OFF
- **Síntoma:** OFF rellena con ceros hasta 13 dígitos; el escáner entrega 8 o 12.
- **Solución:** `normalizar_ean` devuelve `0 + UPC-A` (13), recupera los EAN-8 que vienen
  como `00000xxxxxxxx` y descarta EAN de balanza (empiezan con 2) y dígitos
  verificadores inválidos. El EAN de ejemplo `7791234567890` del seed tiene dígito
  inválido: es manual y no entra en el emparejamiento.

### El volcado completo de OFF trae NUL; los CSV de SEPA, BOM y NUL
- **Síntoma:** `_csv.Error: line contains NUL` a los 60 s de correr con el volcado
  completo (la muestra de 30 MB andaba bien).
- **Solución:** filtrar `\0` línea por línea antes del lector CSV (con test). En SEPA
  además 9 de 16 archivos empiezan con BOM: abrir con `utf-8-sig`. Moraleja: probar con
  el volcado completo antes de dar por bueno un ETL.

### Las descargas grandes de SEPA se cortan
- **Síntoma:** `curl: (18) Transferred a partial file` y zips truncados («End-of-central-
  directory signature not found»).
- **Solución:** reintentar y validar con `unzip -tq`; el servidor no soporta reanudar.

### SEPA: zip interno roto y «1 unidad»
- **Síntoma:** `BadZipFile: File is not a zip file` a mitad de la carga; y 813 conflictos
  falsos de tamaño contra OFF (tras el arreglo quedan 157 reales), casi todos «1 u» (SEPA) vs «400 g» (OFF).
- **Causa:** el zip diario trae algún zip de comercio vacío (0 bytes); y SEPA pone la
  cantidad de envases («1 UNI») en la presentación.
- **Solución:** saltar y contar los zips internos inválidos; no tomar «1 u» como tamaño y
  no comparar tamaños de familias distintas (masa/volumen/unidades).

### `$1` sin tipo en sentencias con asyncpg
- **Síntoma:** `could not determine data type of parameter $1` al usar el parámetro
  en un `select`/`case`. **Solución:** castear (`$1::text`).

### Decisiones del corte 7
- Prioridad por defecto `manual > sepa > off`; SEPA para Argentina, OFF para vecinos:
  `make etl-off` filtra por países (`OFF_PAISES`). Medido: 132 k productos = 75 MB.
- Un ETL por fuente (`etl/<fuente>/`) sobre una capa mínima común; la fusión se hace
  con SQL por lotes (`COPY` a tabla temporal), no fila por fila.
- Los campos que el admin resuelve se **bloquean con un trigger** (integridad en
  Postgres); los ETL ni lo intentan, y si alguien lo intenta a mano falla.
- Los desacuerdos no se reabren una vez vistos (`unique` sobre el desacuerdo completo).
- Los ETL no tienen CI contra datos reales: los tests usan un CSV generado y la base
  local; **los datos de prueba empiezan con `79999`** y se limpian solos.
- Medido con el volcado completo: 4,08 M productos, 2,4 GB en la base, 14 min de carga,
  14 k productos argentinos (ver `docs/05-fuentes-catalogo.md`).

### ETL de locales (OSM / sucursales de SEPA)
- **Síntoma:** `ModuleNotFoundError: osmium` al correr `make etl-osm` o los tests.
- **Causa:** `pyosmium` es dependencia solo del ETL y el venv se creó antes.
- **Solución:** `backend/.venv/bin/pip install -e "backend[dev,etl]"` (`make venv` en un
  venv nuevo ya lo instala).
- **Síntoma:** `AttributeError: 'NoneType' ... strip` al leer `sucursales.csv` de SEPA.
- **Causa:** filas con menos columnas que la cabecera: `csv.DictReader` rellena con None.
- **Solución:** leer cada campo con `(fila.get(k) or "")`.
- **Dato útil:** Geofabrik no parte Argentina por provincia; se baja el país (~436 MB,
  unos 10 min) y se recorta con el límite administrativo `ISO3166-2=AR-N` del mismo archivo.
  El mismo comercio mapeado como `node` y como `way` se vincula a un solo local (anti-duplicados).

---

## Precios vigentes cerca del usuario (corte 8, ajustes tras la prueba en el celular)

- **Decisión:** el filtro por radio vive en el backend (`config.radio_precios_m`,
  5000 m), porque mezclar precios de lugares a miles de km confunde. El orden
  (precio, cercanía, frescura) y el «Mostrar más» son de la app: no cambian qué
  datos se devuelven.
- **Síntoma:** «No puedo conectar con el servidor» en el celular, con el backend
  sano y alcanzable desde el navegador del celular. **Causa:** se había instalado
  un APK viejo con otra URL de API. **Solución:** desinstalar e instalar el APK
  recién generado; ver `strings` de `assets/flutter_assets/kernel_blob.bin` para
  confirmar la URL compilada.
- **Síntoma:** nada responde y `docker ps` está vacío. **Causa:** Docker o el stack
  estaban apagados. **Solución:** `make up` y `docker compose up -d --build backend`.
- **Nota de Flutter:** en `mapa_precios.dart`, `Path` es de `flutter_map`
  (`Path<LatLng>`): para dibujar con `Canvas` usar `ui.Path` (`import 'dart:ui' as ui`).

## Geofence al cargar un precio (corte 6)

- **Decisión:** la distancia la calcula el backend con PostGIS
  (`st_distance` sobre `geography`, en metros) y rechaza con 403 + `detail.codigo`
  (no 422, que la app ya usa para «precio inválido»). `ApiException` ahora guarda el
  `detail` de la respuesta para poder mostrar «Estás a 480 m».
- **Tests:** las cargas de los tests parten de las coordenadas del propio local
  (`tests/db.py::cuerpo_carga`). Ojo: el UUID `…0001` es el local del seed, no sirve
  como «local inexistente».
- **Límite conocido:** la ubicación la informa el celular; una ubicación simulada la
  falsifica (se mitiga con reputación, corte 9).

## Anti-spam (corte 9)

- **Síntoma:** tras activar `modo_acceso`, los tests viejos de `/v1/auth/anonymous`
  devuelven 403. **Causa:** el default (código y seed) es `solo_invitacion`.
  **Solución:** los tests del proxy fijan `modo_acceso = "abierto"` con la fixture
  `config_temporal` (ahora en `conftest.py`); los de acceso viven en
  `tests/test_anti_spam.py`.
- **Síntoma:** un test pasa solo y falla en la suite con 429. **Causa:** el rate limit
  por IP vive en memoria del proceso y el `TestClient` siempre es la misma IP.
  **Solución:** fixture `autouse` en `conftest.py` que reinicia el limitador en cada
  test.
- **Síntoma:** `make migrate` falla con `MigrationMissingLocalError … Remote migration
  versions not found in local migrations directory`. **Causa:** el Supabase local es
  uno solo y lo comparten todos los worktrees: otra rama ya aplicó una migración que
  esta rama no tiene. **Solución:** aplicar a mano la migración propia
  (`psql "$DATABASE_URL" -f supabase/migrations/<archivo>.sql` y un `insert` en
  `supabase_migrations.schema_migrations (version, name)`), o traer la otra rama. En
  CI (base vacía) no pasa.
- **Detrás de un proxy, el rate limit frena a todos o no frena a nadie.** **Causa:**
  sin `PROXY_HOPS` se usa la IP del socket, que detrás de un proxy es la del proxy.
  **Solución:** `PROXY_HOPS=<cantidad de proxies confiables>` (1 con un solo proxy); se
  toma la IP desde la derecha de `X-Forwarded-For`. Con un valor de más, el cliente
  puede falsificar su IP.

---

## Panel web de admin (corte 11)

- **Decisión:** login con email y contraseña de GoTrue vía `POST /v1/admin/login`; solo
  entra `rol = 'admin'`. Crear el admin: `make admin-crear EMAIL=...`. Detalle y
  motivos en `docs/04` §8. Un anónimo promovido con `make admin` **no** entra al panel
  (no tiene credenciales).
- **Síntoma:** `AmbiguousParameterError: could not determine data type of parameter $1`
  (todos los endpoints en 500) tras ampliar el `insert into usuarios` de `app/auth.py`.
  **Causa:** el mismo `$1` se usaba como `uuid` (columna) y dentro de un `case when $4
  then $1 end`; asyncpg no infiere el tipo. **Solución:** castear explícito
  (`$4::boolean`, `$1::uuid`).
- **Síntoma:** usuarios nuevos con `anonimo_auth_id` nulo aunque sean anónimos.
  **Causa:** había un backend viejo (otra imagen Docker) corriendo contra la misma base
  ya migrada: su `insert` no conoce las columnas nuevas. **Solución:**
  `docker compose up -d --build backend` para que corra el código nuevo.
- **Síntoma:** `make admin-crear` con un email que ya existe no devuelve el id.
  **Causa:** GoTrue responde el signup de un email existente sin sesión. **Solución:**
  el CLI cae a iniciar sesión con la contraseña y toma el id de ahí (si la contraseña
  no coincide, falla con el motivo).
- **Síntoma:** el panel dice «No puedo conectar con el backend» o el navegador
  bloquea por CORS al abrirlo desde otra máquina. **Causa:** el origen
  (`http://192.168.x.x:8080`) no está en `CORS_ORIGINS`. **Solución:** agregarlo en `.env`
  y reiniciar el backend. La URL del backend sale de `admin-web/public/config.js`
  (mismo host que el panel, puerto 8000).
- **Gotcha de Alpine:** `x-model.debounce` junto con `@input` dispara el `@input` con el
  valor viejo. Se usa `x-model` plano y `@input.debounce.400ms`.
- **Gotcha de tests:** `auditoria_admin` es solo-agregar, así que los tests dejan filas que
  no se pueden limpiar (como los usuarios de prueba, que ya se acumulaban). No usar la
  auditoría para contar filas totales en los tests: filtrar por `entidad_id`.

### Fichas del panel (segunda iteración)
- **Decisión:** el rol se puede cambiar desde `/v1/admin` (no desde la API pública); ver
  `docs/04` §8 por qué y qué salvaguardas lleva.
- **Síntoma:** la ficha no podía preguntar «¿es un duplicado?» al recibir el 409.
  **Causa:** `api()` del front solo propagaba el mensaje del error, no el status ni el
  `detail` estructurado. **Solución:** el `Error` lleva `status` y `detalle`; la ficha
  detecta `local_duplicado` y reintenta con `forzar`.
- **Síntoma:** el enlace «ver precios» de una ficha abría la lista sin filtrar.
  **Causa:** se cerraba la ficha (`ficha = null`) *antes* de leer `ficha.id` en el mismo
  handler. **Solución:** una sola función (`verPrecios`) que cierra y filtra con el id ya
  leído. Regla: en handlers de Alpine, leer lo que haga falta de la ficha antes de cerrarla.
- **Síntoma:** un test que corrige un local con nombre fijo dio 409 solo en algunas
  corridas. **Causa:** una corrida anterior que falló en la limpieza dejó un local con el
  mismo nombre y lugar, y ahora el chequeo de duplicados lo detecta. **Solución:**
  nombres con sufijo aleatorio en los tests y limpiar los precios de los locales `adm-%`
  antes de borrarlos (si no, el `delete` falla por la clave foránea y deja basura).
- **Dato útil:** esta máquina no tiene `node`, así que el JS del panel no se chequea con
  `node --check`: se prueba en el navegador (consola sin errores y la ficha abierta).

### `make up` falla con «port is already allocated» (0.0.0.0:8000 o :8080)
- **Síntoma:** `Bind for 0.0.0.0:8000 failed: port is already allocated`; un `make down`
  seguido de `make up` da el mismo error, y vuelve a pasar cada vez que se cambia de
  carpeta (checkout principal ↔ worktree).
- **Causa:** Docker Compose nombraba el proyecto por la **carpeta**. El checkout principal
  (`almacenero`) y cada worktree (`admin-web-e8bb1c`, `anti-spam-e830d6`…) eran proyectos
  distintos con los mismos puertos. Un stack que otra sesión (o vos) dejó corriendo en
  *otra* carpeta seguía ocupando 8000/8080, y `make down` solo baja el proyecto de la
  carpeta donde se corre (el `supabase stop` sí es global).
- **Solución definitiva:** `docker-compose.yml` fija `name: almacenero`. Ahora hay **un solo
  proyecto** sin importar la carpeta: `make up` desde cualquier checkout *reemplaza* los
  contenedores por los de ese código, y `make down` los baja desde cualquier carpeta. Una
  rama vieja que todavía no tiene esa línea sigue chocando hasta que se la actualice
  (merge o rebase de `main`).
- **Diagnóstico si pasa igual:**
  ```bash
  docker compose ls -a          # ¿hay un proyecto con otro nombre?
  docker ps -a --format '{{.Names}}\t{{.Ports}}\t{{.Status}}' | grep -v supabase
  lsof -nP -iTCP:8000 -sTCP:LISTEN
  ```
  Bajar el proyecto viejo con su nombre: `docker compose -p <nombre> down`.
- **Ojo:** el stack que queda corriendo es el del código de la última carpeta donde se
  hizo `make up` (el del checkout principal no tiene el panel hasta que se mergee).
- **Probar una rama sin tocar el stack levantado:** `uvicorn` en otro puerto + servir
  `admin-web/public` con un `config.js` apuntando ahí (y `CORS_ORIGINS` con ese origen).

## «No pudimos conectar con el servidor» en el celular (corte 9)

- **Síntoma:** el celular y el servidor están en la misma red y la app dice «No pudimos
  conectar con el servidor». **Causa (la que nos pasó):** se instaló un APK viejo. Los
  APK se llaman todos `app-debug.apk`, así que no hay forma de distinguirlos, y un APK
  anterior al corte 9 no manda código de invitación: el backend contesta 403 y la app
  mostraba el mismo cartel que para «sin red». **Solución:** la pantalla principal ahora
  muestra versión, commit, servidor, estado de `/v1/health` e IP del celular, y el error
  dice «El servidor respondió 403 (…)» cuando hay respuesta. Leer eso antes de adivinar.
- **Cómo separar las causas, de lo más barato a lo más caro:**
  1. ¿La versión de la pantalla es la que acabás de compilar? Si no, es otro APK.
  2. «Estado: sin conexión» → es la red: IP del celular en otra subred que la del
     servidor, Wi-Fi con «aislamiento de clientes» (típico en redes de invitados), IP del
     servidor cambiada desde la compilación (comparar «Servidor» con `ipconfig getifaddr
     en0`), firewall de macOS (`socketfilterfw --getglobalstate`).
  3. «Estado: respondió error N» o «responde» con el cartel de error → la red anda; es
     el backend (ver `docker compose logs backend`).
- **Probar la red sin el celular:** `curl http://<IP-del-servidor>:8000/v1/health` desde
  otra máquina de la misma red.
- **Quién está sirviendo el puerto 8000:** el compose tiene nombre fijo, así que el último
  `make up` (desde cualquier worktree) reemplaza al backend. `docker inspect
  almacenero-backend-1` y la etiqueta `com.docker.compose.project.working_dir` dicen de
  qué carpeta salió el código.

## Rate limit por IP detrás de Docker Desktop (corte 9)

- **Síntoma:** el celular recibe 429 («Demasiados intentos») aunque casi no lo usaste, y
  en el log del backend todos los pedidos vienen de `192.168.65.1`. **Causa:** Docker
  Desktop (Mac) enmascara el origen: toda conexión desde afuera del contenedor, la del
  celular, la de un `curl` y la de los tests, llega con esa misma IP. El cupo por IP
  (`auth_altas_por_hora_ip`) pasa a ser UNO para todos, y los intentos fallidos de un
  código también cuentan. **Solución en desarrollo:** el seed lo sube a 100; para vaciar
  el contador al instante, `docker restart almacenero-backend-1` (vive en memoria).
  **En producción:** con la IP real (`PROXY_HOPS`, ver arriba) el cupo vuelve a ser por
  persona y el valor es 10.

## «No me pide el código de invitación» (corte 9)

- **Síntoma:** instalás el APK nuevo y la app abre directo en «Escanear código», sin
  pedir invitación. **Causa:** la app ya tenía una sesión guardada (de antes de activar
  las invitaciones). El código se pide solo cuando hay que CREAR un usuario; con sesión
  vigente, o renovable con el refresh token, no hace falta. **Solución:** borrar los
  datos de la app (Ajustes → Apps → Almacenero → Almacenamiento → Borrar datos) o
  desinstalarla. Un usuario nuevo siempre cae en la pantalla del código.
- **Un PIN «usado» que nadie usó:** si el alta falló después de gastarlo (proveedor de
  auth caído) el uso se devuelve solo; si el PIN figura usado en el panel, alguien creó
  un usuario con él (ver «Usado por»).

---

## Moderación y baja de cuentas (corte 12)

Decisiones en `docs/04` §9.

- **Síntoma:** en un worktree nuevo, `make test` falla con `backend/.venv/bin/python: No
  such file or directory` y el backend no encuentra `DATABASE_URL`. **Causa:** un worktree
  es un checkout limpio: trae lo que git versiona, y `.env` y `backend/.venv` están en
  `.gitignore`, así que no se copian. **Solución:** `cp <checkout principal>/.env .env` y
  `make venv`. (No se commitean: son secretos y binarios locales.)
- **Síntoma:** una cuenta dada de baja «revive»: la app vuelve a mostrar el home con otro
  alias. **Causa (evitada):** si el backend rechazara con 401, la app lo interpreta como
  «sesión perdida» y se crea una cuenta anónima nueva (`AuthRepository._resolve`).
  **Solución:** la baja responde **403** con `detail.codigo = cuenta_baja`, tanto en
  `current_user` como en `/auth/refresh`; la app lo muestra como pantalla final y no pide
  sesión. La defensa contra el alta nueva es el PIN (`modo_acceso = solo_invitacion`).
- **Síntoma:** el usuario de baja sigue entrando un rato. **Causa:** nada, salvo que el
  backend viejo siga corriendo: el último que corrió `make up` es el que sirve y puede ser
  el de otra rama sin este corte. **Solución:** `make up` desde la rama correcta. Con el
  código del corte, la baja vale en el **siguiente request**, también con el token vigente
  (cada request consulta la fila del usuario).
- **Síntoma:** el panel dice `el valor no puede ser negativo` al editar
  `karma_umbral_aviso`. **Causa:** la validación genérica de `/v1/admin/config` rechaza
  números negativos. **Solución:** los dos umbrales de karma tienen una regla propia
  (cero o negativos, y la restricción nunca por encima del aviso).
- **Síntoma:** un test que prepara estado con `sql("select set_config(...); update ...")`
  falla con `cannot insert multiple commands into a prepared statement`. **Causa:**
  asyncpg no ejecuta varias sentencias con parámetros. **Solución:** un helper que abre la
  transacción y las ejecuta por separado (`tests/db.py`: `poner_karma`,
  `poner_estado_sin_fecha`). El `set_config(..., true)` solo vale dentro de la transacción.
- **Síntoma:** el panel abre con «no tenés permiso para esto» y una sesión «prueba@local».
  **Causa:** el navegador conservó la sesión de otro usuario (localStorage) que no es
  admin. **Solución:** «Salir» y entrar con el admin (`make admin-crear`).
- **«Entró con el PIN: sin registro» en la ficha.** El PIN de un solo uso queda atado a
  quien lo usó; el código **compartido** (`almacenero-dev`) solo guarda al último. Para
  rastrear a quien vuelve después de una baja, repartir PINs individuales.
- **Dispositivo (ANDROID_ID).** Un dispositivo asociado a una cuenta de baja no puede
  crear otra (403 `cuenta_baja` antes de gastar el PIN). **Síntoma típico:** probás con el
  mismo celular un alta nueva después de dar de baja a tu cuenta de prueba y la app
  muestra «cuenta dada de baja». **Causa:** es lo esperado. **Solución:** reactivar la
  cuenta vieja desde el panel (deja de bloquear) o probar desde otro celular. Las cuentas
  anteriores a esta versión se asocian al dispositivo la próxima vez que renuevan sesión
  (`/auth/refresh`), no antes. Solo se guarda el hash (`tabla dispositivos`).
- **Síntoma:** probás una feature nueva del backend desde el celular y no hace nada.
  **Causa:** el contenedor del backend sigue con la imagen vieja (el APK es nuevo, el
  servidor no). Comprobación: `docker exec almacenero-backend-1 ls app/services`.
  **Solución:** `docker compose up -d --build backend admin-web` (migraciones:
  `make migrate`). Cada corte con backend nuevo necesita esto antes de probar.
- **Síntoma:** dar de baja a alguien que está quieto en una pantalla no muestra nada.
  **Causa:** el backend no puede avisarle; la app se entera solo cuando hace un pedido.
  **Solución:** `VigilanteDeCuenta` consulta `/me` cada 30 s y al volver a la app.

## Backup, simulacro de restauración y servidor dormido (ajustes previos al corte 10)

- **`make backup`** hace `pg_dump` (formato custom, solo el esquema `public`) de
  `DATABASE_URL` a `backups/almacenero-<fecha>.dump`, más un `.conteos` con las filas de
  `locales`, `productos_canonicos`, `precios` y `usuarios` en ese momento. `backups/` está
  en `.gitignore`: **un backup tiene datos de personas, no se commitea ni se sube a un
  lugar público**. **`make restore-test`** crea la base `almacenero_restore_test` en el
  mismo servidor, restaura ahí el último dump, compara los conteos y la borra (también si
  falla). Nunca escribe en la base real.
- **Síntoma:** `pg_restore` falla con `unrecognized configuration parameter
  "transaction_timeout"`. **Causa:** el `pg_dump` del Mac es 17 y escribe un `SET` que los
  servidores 15 y 16 (el de `supabase start` es 15) no conocen. **Solución:** el simulacro
  filtra esa línea al restaurar (`pg_restore -f - | grep -v ... | psql`). Si más adelante
  el servidor es 17, el filtro sobra pero no molesta.
- **Síntoma:** al restaurar, `schema "public" already exists`. **Causa:** el dump
  incluye `CREATE SCHEMA public` y toda base nueva ya tiene `public`. **Solución:** se
  filtra esa línea. Las extensiones (`postgis`, `pg_trgm`, `unaccent`) **no** vienen en un
  dump de `--schema=public`: el simulacro las crea antes de restaurar. En una base nueva
  de verdad hay que correr primero las migraciones (o crear las extensiones a mano).
- **Síntoma:** `permission denied for table spatial_ref_sys`. **Causa:** esa tabla es de
  PostGIS (la crea la extensión, con otro dueño); no es un dato nuestro. **Solución:**
  el backup la excluye (`--exclude-table=spatial_ref_sys`).
- **En producción:** `DATABASE_URL` tiene que ser la conexión **directa** de Supabase
  (puerto 5432), no el pooler en modo transacción: `pg_dump` no anda por ahí. El backup
  incluye solo `public`; los usuarios de Supabase Auth (`auth.users`) NO están: ver el
  punto de Auth del plan de escape en `docs/04`.
- **Servidor dormido (Fly.io).** El backend se apaga solo sin tráfico; el primer pedido
  espera el arranque en frío (varios segundos). La app (`ApiClient`) espera cada intento
  `API_TIMEOUT_S` segundos (20 por defecto; se cambia al compilar: `make apk
  API_TIMEOUT_S=40`), muestra «Despertando servidor…» si un pedido pasa de 4 s y reintenta
  con backoff (1 s, 2 s) **solo** lo que se puede repetir sin efectos: los GET y
  `/auth/refresh`. Un POST común (cargar un precio) no se reintenta solo: si el servidor lo
  procesó y se perdió la respuesta, quedaría duplicado. **Síntoma:** «El servidor tardó
  demasiado en responder (N s)» = hay red pero el servidor no contestó (dormido, caído,
  muy lento): subir `API_TIMEOUT_S` o revisar el backend. «Sin conexión con el servidor» =
  no hay red o la URL es inalcanzable.

## Pantalla «Acerca de» y atribuciones (ajustes previos al corte 10)

- **Dónde está.** Ícono ⓘ en la barra del inicio → «Acerca de»: nombre y versión, la
  tarjeta de versión/compilación/servidor/IP (se mudó desde el pie del inicio; sigue
  accesible aunque no haya conexión, porque el ícono vive en la barra del inicio también
  cuando falla `/me`), las tres fuentes con su licencia y enlaces (textos literales de
  `docs/05` §4.3) y el botón de licencias de librerías (`showLicensePage`).
  **Si cambia un texto de `docs/05`, cambiarlo también en `lib/ui/acerca_screen.dart`**
  (`fuentesDatos`); el test de la pantalla compara contra esa lista.
- **Mapa:** ya mostraba «© OpenStreetMap contributors» (`SimpleAttributionWidget` en
  `mapa_precios.dart`); ahora hay un test que lo exige. El enlace a la licencia vive en
  «Acerca de», no en el mapa.
- **Enlaces:** `url_launcher` abre el navegador; en Android 11+ hace falta declarar el
  intent `VIEW https` en `<queries>` del `AndroidManifest.xml` (ya está). **Síntoma si
  falta:** tocar un enlace no hace nada.

## Normalizador del catálogo (corte 13)

- **Síntoma:** el medidor tardaba más de 2 minutos en 134 mil productos (y subía con el
  tamaño del lookup de marcas). **Causa:** se reconstruían en cada llamada el conjunto de
  claves de marca y la lista de alias de la marca (O(1 600) por producto). **Solución:**
  `_claves_de_marca()` cacheada con `lru_cache`; ahora corre en ~10 s. En una función que se
  llama millones de veces no se arma nada a partir del diccionario global.
- **Síntoma:** `750 cm3` no se interpretaba como tamaño (ni en el campo de SEPA ni en el
  nombre). **Causa:** el patrón de unidades de `tamano.py` era `[a-zA-Z]+` y `cm3` tiene un
  dígito. **Solución:** `[a-zA-Z]+[0-9]?`.
- **Síntoma:** nombres que quedaban en una palabra («Celeste», «Alfombra») o perdían «Pvc».
  **Causa:** la «marca» de SEPA a veces trae la palabra del producto («Suavizante Vivere») y
  `Pvc`/`Pet` también es un material. **Solución:** la marca no se saca del nombre si lo deja
  en menos de 2 palabras, y las palabras de envase sueltas (`pet`, `bot`, `pvc`) solo se
  sacan del nombre cuando ese nombre también trae un tamaño.
- **Dato a tener en cuenta:** el campo de tamaño de SEPA miente más de lo esperado (coma
  corrida: `1.5 g` con el nombre en `1.5 kg`; `1 g` imposible; `100 l` por `1 l`): ~1 000
  casos. Si el campo y el nombre difieren por una potencia de diez, o el campo es ≤ 1 g/ml,
  gana el nombre (`tamano_campo_corregido`); el resto de discrepancias queda `dudoso`.

## Calidad del catálogo en la base (corte 14)

- **Síntoma:** volver a pasar el normalizador por el catálogo ya normalizado cambiaba
  cientos de filas (y marcas dudosas dejaban de serlo). **Causa:** el normalizador no era
  idempotente en casos reales que los tests no cubrían: dos sufijos de SEPA
  (`BOT-1000-cc. BOT-1000-ml.`), la marca repetida en el nombre (`… - Itambé - Itambé`),
  `oBLEAS` (primera letra en minúscula), `c/c/a`, `S/E-40-un.`, la marca que deja
  «X 591» o «Sin Azúcar» como nombre. Además, los motivos que salen de comparar el dato
  crudo con el nombre (`tamano_en_conflicto`, `abreviado`) no se vuelven a ver en un nombre
  ya limpio. **Solución:** se arreglaron esos casos y los motivos «pegajosos» viajan con la
  fila (`_PEGAJOSOS` en `etl/comun/catalogo.py`). **Cómo chequearlo:** correr
  `make catalogo-renormalizar` dos veces; la segunda debe decir «Cambiarían: 0». Y
  comparar `normalizar(normalizar(x))` contra `normalizar(x)` sobre `producto_fuentes`.
- **Síntoma:** `ruff format etl` reformateó 15 archivos que no eran míos. **Causa:** se
  corrió el `ruff` del sistema, no el del venv, sin `--config backend/pyproject.toml` (el
  Makefile sí lo pasa). **Solución:** usar siempre `make lint` (o
  `backend/.venv/bin/ruff … --config backend/pyproject.toml`).
- **Síntoma:** un producto `descartado` no se puede cargar ni buscar en la app. **Esto es a
  propósito** (Doc 7 §5): hasta que alguien lo complete desde el panel (o una fuente lo
  mejore), la app contesta «no encontrado». Se ve con el filtro «Descartado» del panel.

---

## Rol moderador y sugerencias (corte 15)

### Error en consola al buscar un EAN que no existe en «Alta / corrección»

- **Síntoma:** `Cannot read properties of null (reading 'estado_calidad')` al buscar un EAN
  nuevo; el formulario igual se ve.
- **Causa:** `x-show` **evalúa** su expresión y las de sus hijos aunque oculte el bloque, así
  que `alta.d.estado_calidad` revienta cuando `alta.d` es `null` (el alta).
- **Solución:** envolver lo que depende de datos que pueden faltar en `<template x-if="...">`
  (que no renderiza ni evalúa) o usar `?.`.

### `auditoria_admin` rechaza la entidad `sugerencia`

- **Síntoma:** `CheckViolationError ... auditoria_admin_entidad_check` al aprobar una sugerencia.
- **Causa:** la entidad auditable es una lista cerrada en un `check`; cada entidad nueva
  necesita ampliarla en su migración (pasó con `invitacion` y ahora con `sugerencia`).
- **Solución:** `drop constraint` + `add constraint` con la lista ampliada, en la migración.

### El panel de prueba en otro puerto dice «No puedo conectar con el backend»

- **Síntoma:** al probar el panel en un puerto distinto de 8080, el login falla aunque el
  backend responda.
- **Causa:** CORS: solo se permite `CORS_ORIGINS` (por defecto el panel en 8080).
- **Solución:** levantar el backend de prueba con `CORS_ORIGINS=http://localhost:<puerto>`.

### «Failed to fetch» al aprobar una sugerencia (pack de 1)

- **Síntoma:** en el panel, aprobar una sugerencia muestra «Failed to fetch»; en el log del
  backend, `productos_canonicos_pack_cantidad_check`.
- **Causa:** el celular mandaba `pack_cantidad: 1` y la base exige `pack_cantidad > 1` («pack de
  1» no es un pack). Al ser un 500 sin cabeceras CORS, el navegador lo muestra como «Failed to
  fetch» y no como un error de la API.
- **Solución:** `Cambios` guarda «pack de 1» como «sin pack», y un dato que la base rechaza al
  aprobar responde 422 en vez de 500. Las sugerencias viejas ya guardadas con pack 1 también se
  aprueban. Ante un «Failed to fetch» en el panel: `docker compose logs backend`.
  **Seguimiento:** ya no hay 500 mudos (Doc 4 §10-E): un error inesperado responde con CORS y una
  `referencia` que se busca en esos logs, y las violaciones de la base explican la regla.

### Un error del backend no dice qué regla se violó

- **Síntoma:** una acción falla con «Error 500», «Failed to fetch» o un mensaje técnico, y quien
  la hizo no sabe qué corregir.
- **Causa:** una violación de integridad (check, unique, trigger) o un dato viejo que el modelo ya
  no acepta subía sin manejar.
- **Solución:** Doc 4 §10-E. Cada regla tiene un código, un mensaje y una guía; el mensaje se
  edita en Configuración → «Mensajes de error». Si falta una regla para un constraint nuevo, cae
  en `dato_invalido` mostrando el nombre de la restricción: agregalo a `POR_CONSTRAINT` y a
  `REGLAS` en `backend/app/services/reglas.py`.

### `ImportError: cannot import name 'UTC' from 'datetime'` al correr el ETL local

- **Síntoma:** un módulo de `etl/` falla al importar con `cannot import name 'UTC'`.
- **Causa:** `backend/.venv` usa el Python del sistema (3.10 en esta Mac) y `datetime.UTC` es de
  3.11+. La imagen Docker usa 3.12, así que el error solo aparece en local.
- **Solución:** `datetime.timezone.utc` (el proyecto declara `requires-python >= 3.10`).

### El simulacro del CSV curado dice «se actualizan» todo el catálogo

- **Síntoma:** `make catalogo-csv-importar ARCHIVO=…` muestra casi todos los EAN como actualizados,
  y el ejemplo es `origen: 'sepa' → 'curado'`.
- **Causa:** al importar, el origen pasa a `curado` (prioridad más alta que SEPA y OFF) aunque los
  datos sean iguales; se contaba como cambio.
- **Solución:** «actualizados» cuenta solo cambios de datos; el cambio de fuente sale aparte
  («pasan a figurar como `curado`»).

### «Este archivo ya se importó» al reimportar un CSV curado

- **Síntoma:** `APLICAR=1` no hace nada y avisa el lote anterior.
- **Causa:** `catalogo_lotes` ya tiene ese `sha256` con la misma `NORMALIZADOR_VERSION`: importar
  de nuevo no aportaría nada (la importación es idempotente).
- **Solución:** si hace falta igual (p. ej. otra fuente pisó lo curado), `FORZAR=1`.

### Un ETL lanzado desde el panel se queda «en cola» para siempre

- **Síntoma:** en la sección ETL el estado no sale de `en_cola`.
- **Causa:** (a) el ETL es de ejecutor **local** y no hay un `make etl-worker` corriendo contra esa base;
  o (b) es **web** y el backend se levantó con `ETL_WEB_ACTIVO=false`, o con una imagen vieja sin `etl/`.
- **Solución:** (a) correr `make etl-worker` con el `DATABASE_URL` de la base que mira el panel; (b)
  `make up` (reconstruye la imagen con el contexto en la raíz del repo) y no desactivar el ejecutor.

### Una ejecución quedó «corriendo» y no avanza

- **Causa:** el ejecutor murió (se apagó el backend o se cortó el worker) a mitad de camino.
- **Solución:** no hay que hacer nada: sin latido por 2 minutos pasa sola a `fallo` y el ejecutor puede
  tomar la siguiente. Cada lote es una transacción, así que no quedan datos a medias; volver a lanzar es
  seguro (los ETL son idempotentes).

### `docker compose build` no encuentra `etl/` (o la imagen vieja no tiene `etl`)

- **Síntoma:** el backend arranca pero el ejecutor web falla con `No module named 'etl'`.
- **Causa:** el Dockerfile del backend se construía con `./backend` como contexto, que no incluye `etl/`.
- **Solución:** el contexto es la raíz del repo (`docker-compose.yml`: `context: .`, `dockerfile:
  backend/Dockerfile`; `.dockerignore` deja afuera `app/`, `etl/data/` y los tests). Cualquier otro build
  (CI, Fly) tiene que usar ese mismo contexto.

### `asyncio.TimeoutError` no se atrapa como `TimeoutError` en Python 3.10

- **Síntoma:** un `except TimeoutError` alrededor de `asyncio.wait_for` no atrapa nada en la Mac (3.10).
- **Causa:** recién desde 3.11 `asyncio.TimeoutError` es el mismo `TimeoutError`.
- **Solución:** `except asyncio.TimeoutError` (vale en las dos).

### `auditoria_admin_entidad_check` al auditar una acción nueva

- **Síntoma:** una acción nueva del panel falla con 422 `dato_invalido (auditoria_admin_entidad_check)`.
- **Causa:** la entidad de auditoría es una lista cerrada en la base.
- **Solución:** sumarla al check en una migración (el corte 18 sumó `etl`).

### «Medir la calidad» da siempre lo mismo, cambie lo que cambie en los parámetros

- **Síntoma:** en el panel (ETL → Medir la calidad) el resultado es idéntico con `muestra` 1000 o
  130000 y con `estado` descartado o completo.
- **Causa:** (1) los parámetros solo afectaban la lista de ejemplos, y (2) esa lista solo incluía
  productos cuyo nombre el normalizador cambiaría; como el catálogo ya está renormalizado, no había
  ninguno y la lista salía vacía. Además el reporte no decía qué reglas se aplicaban.
- **Solución:** los ejemplos son ahora productos al azar del estado pedido (con puntaje y motivos), el
  informe aclara cómo leerlo («cambiaría: 0» = ya normalizado) e incluye qué reglas se aplicaron y por qué
  bajan de puntaje (Doc 7 §14). Para ver las reglas sobre un dato crudo: ETL → «Probar el normalizador».

### `ruff format` sobre `etl/` reescribe medio repo

- **Síntoma:** después de formatear, `git status` muestra decenas de archivos de `etl/` modificados que no
  tocaste (comas finales, líneas partidas distinto).
- **Causa:** `ruff` suelto usa su configuración por defecto (88 columnas), no la del proyecto
  (`backend/pyproject.toml`, 100).
- **Solución:** correr siempre `make lint` o `ruff … --config backend/pyproject.toml etl`. Si ya pasó,
  `git checkout -- <archivos que no editaste>` y reformatear los tuyos con esa config.

### `campos_bloqueados solo se modifica al resolver un conflicto` (o «nombre bloqueado…») desde un script

- **Síntoma:** un `UPDATE` de `campos_bloqueados` o de un campo bloqueado falla aunque hiciste
  `select set_config('app.catalogo_write', 'on', true)`.
- **Causa:** `set_config(..., true)` vale solo dentro de la transacción; en una conexión en autocommit
  cada sentencia es su propia transacción y el permiso se pierde antes del `UPDATE`.
- **Solución:** `async with conn.transaction():` alrededor de las dos sentencias (lo hace
  `services.catalogo.aplicar` y `etl/curado/importar.py::_restaurar`).

### Un export no se puede volver a importar: «ean_digito_verificador» en un producto cargado a mano

- **Síntoma:** reimportar un export de la base informa 1 fila inválida por dígito verificador.
- **Causa:** un producto `manual` (demo/código interno) tiene un EAN con verificador inválido; la base lo
  acepta (solo exige 8–14 dígitos) pero el importador validaba todo con GS1.
- **Solución:** en un v2 las filas `origen = manual` se aceptan con solo el largo (Doc 9 §5.4).

### «Pasan a figurar como `curado`: 134503» al reimportar un export de la base

- **Síntoma:** el simulacro de reimportar un v2 decía que casi todos cambiaban de origen.
- **Causa:** la fusión con `fuente = 'curado'` sube el origen a `curado`, pero en un v2 cada fila ya trae el
  suyo (`off`, `sepa`…).
- **Solución:** el importador restaura el `origen` del archivo (sin degradar nunca un `manual` local); Doc 9
  §5.2. Ahora da 0.

### Una migración aplicada «a mano» en la base compartida y `make migrate` en otras ramas

- **Síntoma:** `remote migration versions not found in local migrations directory` en una rama que no
  tiene la migración.
- **Causa:** `supabase migration up` registra la versión en la base; las ramas sin ese archivo no la
  conocen. La base local es una sola para todos los worktrees.
- **Solución:** cambiar a la rama que la tiene (`git switch feat/etl-panel`). Para cambios aditivos que
  hay que probar desde otro lado, escribir la migración idempotente y aplicarla con `psql -f` (no
  registra la versión; el `make migrate` posterior de la rama correcta la reaplica sin daño).

### El usuario tenía que saber la extensión del export (`.csv.gz`)

- **Síntoma:** el formulario de export rechazaba `catalogo` por no terminar en `.csv`/`.csv.gz`.
- **Causa:** el nombre validaba la extensión en vez de decidir nosotros el formato.
- **Solución:** el export pide solo un nombre y siempre escribe `.zip` (CSV + `LEEME.txt`); si el nombre
  trae `.zip`/`.csv`/`.csv.gz`, se ignora. Al importar se reconoce el formato por los primeros bytes, no
  por la extensión (Doc 9 §2.1).

### Sin migración: dos datos de un mismo local en dos instalaciones

- **Síntoma:** al llevar locales de una base a otra se duplicaban o se pisaba lo que el admin de destino
  ya había corregido.
- **Causa:** no hay un id común entre instalaciones (los uuid son locales a cada base).
- **Solución:** se cruza por los vínculos con OSM/SEPA y, si no, por nombre + distancia (la regla del alta
  de locales); un local existente no se pisa (solo se verifica y se le suman vínculos). Doc 9 §8.

### `make test` falla con `No such file ... backend/.venv/bin/python` en un worktree nuevo

- **Síntoma:** en un worktree recién creado, `cd backend && .venv/bin/python -m pytest` no encuentra el
  intérprete.
- **Causa:** el `.venv` no se versiona: cada worktree tiene el suyo y empieza sin él.
- **Solución:** `make venv` (lo crea e instala `backend[dev,etl]`); `make test` y `make lint` también
  lo crean solos. Los tests igual usan **la misma base local** de los demás worktrees.

### Los eventos de la app no llegan (y nadie se entera)

- **Síntoma:** el celular escanea y `select count(*) from eventos` no sube.
- **Causa posible:** es **a propósito silencioso**: la cola de la app descarta el lote si no hay red, si
  el servidor tarda más de 10 s o si responde error (docs/04 §11.2). Además `producto.escaneado` solo se
  anota cuando la app **sabe** si el producto existe (200 o 404); sin red al buscar el producto no hay
  evento, y los eventos se mandan ~5 s después del primero (o al irse la app a segundo plano).
  Ojo: **los tests de backend usan la misma base** que el celular; los de eventos limpian lo que
  crean, pero filas viejas de antes del fixture (con `ocurrio_en_cliente` de 2001) son de pruebas.
- **Solución:** para depurar, mirar los logs del backend (`docker compose logs backend | grep eventos`):
  un 400 `evento_tipo_desconocido` / 422 `evento_datos_invalidos` explica qué regla se violó. Probar
  con red, escanear un producto, mandar la app a segundo plano y esperar unos segundos.

### La app no manda eventos (o falla algo «nuevo») y el código está bien: backend o APK de otro worktree

- **Síntoma:** una función nueva no hace nada en el celular; en los logs del backend no aparece ningún
  pedido a la ruta nueva (o aparece un 404), aunque los tests pasan.
- **Causa:** el contenedor del backend (`almacenero-backend-1`) y el APK son **compartidos entre todos los
  worktrees**: `make up` y `make apk` pisan el anterior con el código del worktree desde el que se corren. Y
  el número de versión del APK sale de un contador del `.git` común, así que «0.0.16» no dice de qué rama
  viene. Si la última vez se corrieron desde otra rama, el celular o el backend no tienen tu código.
- **Solución:** correr `make up` y `make apk` desde el worktree que se quiere probar. Para comprobarlo:
  el commit en «Acerca de» de la app tiene que ser el de `git rev-parse --short HEAD`, y
  `docker inspect almacenero-backend-1 --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'`
  tiene que dar la carpeta del worktree. Para ver si el backend tiene una ruta:
  `curl -s localhost:8000/openapi.json | grep eventos`.

## Dashboard: almacén de exportaciones y programaciones (corte 19c)

### `make almacen-probar` falla o «no pude leer el S3 local»

- **Síntoma:** `FALLÓ: ...` al probar el almacén, o el export de eventos termina en `fallo` y los eventos
  siguen en la base.
- **Causa posible:** (1) faltan las variables `EXPORT_S3_*` en `.env` (sin ellas se usa el disco, que no
  sirve si el backend corre en Fly); `make up` las completa solo con el S3 del Storage local
  (`supabase status`: `STORAGE_S3_URL` y las claves S3), pero si `.env` ya tenía `EXPORT_S3_ENDPOINT` no las
  toca. (2) Desde el contenedor del backend, `127.0.0.1` es el propio contenedor: por eso el compose usa
  `EXPORT_S3_ENDPOINT_DOCKER` (`host.docker.internal`). (3) Las claves S3 del Supabase local **cambian si se
  recrea el stack** (`supabase stop --no-backup`): hay que volver a copiarlas.
- **Solución:** `make almacen-probar` muestra el detalle. Para regenerar las variables, borrá las líneas
  `EXPORT_S3_*` de `.env` y corré `make up`. El almacén es lo único que decide si se borra: **si no pasa la
  prueba, `eventos_exportar` no borra nada** (diseño en `docs/04` §11.4).

### El S3 alternativo no levanta o sus tests se «saltean»

- **Síntoma:** `pytest -rs` muestra `alternativo: no disponible`.
- **Causa:** el S3 alternativo (SeaweedFS) es **opcional** (perfil `s3-alt` del compose): no arranca con `make up`. Los tests lo usan
  si responde en `127.0.0.1:8333`.
- **Solución:** `make s3-alt-up` (la primera vez baja la imagen y el S3 tarda ~30 s en responder en :8333). Para usarlo como almacén de verdad, poné en
  `.env` `EXPORT_S3_ENDPOINT=http://127.0.0.1:8333`, `EXPORT_S3_BUCKET=exportaciones`,
  `EXPORT_S3_KEY=almacenero`, `EXPORT_S3_SECRET=almacenero-dev-secreto` y corré `make almacen-probar`. La
  La API en :8333 solo responde XML; los archivos se ven en http://localhost:8888/buckets/ (cualquier clave sirve). MinIO no se usa porque ya no publica imágenes públicas
  (Docker Hub y quay.io dan «access denied»). `make s3-alt-down` lo baja (los datos quedan en el volumen).

### Un ETL queda «en cola» y «Ver log» dice «(sin salida todavía)»

- **Síntoma:** encolás un ETL desde el panel (p. ej. exportar catálogo o locales), pasan los minutos y sigue
  en `en_cola`; el log está vacío.
- **Causa:** los ETL pesados (`catalogo_exportar`, `locales_exportar`, importaciones…) tienen ejecutor
  **`local`**: no corren en el backend sino en el worker de tu máquina, y nadie los toma si
  `make etl-worker` no está corriendo. La columna «Dónde» dice `worker local`; el panel ahora además muestra
  hace cuánto esperan y el log explica qué falta. Los livianos (`eventos_exportar`) tienen ejecutor `web` y
  los toma el backend solo.
- **Solución:** correr `make etl-worker` (con `DATABASE_URL` a la base que usa el panel). Una ejecución
  cancelada antes de empezar queda con el log vacío: es normal.

### SeaweedFS en `localhost:8333` solo muestra XML

- **Causa:** `:8333` es la API S3 (para el backend), no tiene pantalla.
- **Solución:** el navegador de archivos es el filer: `http://localhost:8888/buckets/` (y `:9333` es el estado
  del cluster). Para el Storage local de Supabase (el almacén por defecto) usá Studio:
  `http://127.0.0.1:54323` → Storage → bucket `exportaciones`.

### Un `<select>` armado con `x-for` muestra la primera opción en vez del valor del modelo

- **Síntoma:** en el panel (Alpine), un `<select x-model>` cuyas `<option>` salen de un `x-for` arranca en
  la primera opción aunque el estado diga otra (pasó con la granularidad del dashboard y con el ETL de la
  programación).
- **Causa:** el valor del modelo se asigna antes de que existan las opciones.
- **Solución:** para listas fijas, escribir las `<option>` a mano; para listas que llegan de la API, asignar
  el valor después de `await this.$nextTick()`.
