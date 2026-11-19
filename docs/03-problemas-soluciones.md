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
