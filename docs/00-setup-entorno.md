# Doc 0 — Setup del entorno de desarrollo en otra computadora

Todo lo necesario para mover el desarrollo de Almacenero a una máquina nueva (macOS con
Homebrew; en Linux cambian los comandos de instalación pero no las herramientas). Al final hay una
lista de verificación. Los problemas ya vividos con Android/Flutter están en
`docs/03-problemas-soluciones.md` («Armar el entorno desde cero»).

## 1. Qué se instala y para qué

| Herramienta | Para qué la usa el proyecto |
|-------------|-----------------------------|
| **Homebrew** | Instalador de todo lo demás en macOS (<https://brew.sh>). |
| **Git + GitHub CLI (`gh`)** | Repo, ramas y PRs. |
| **Docker Desktop** | El Supabase local y el backend corren en contenedores (`make up`). Darle ≥ 8 GB de RAM. |
| **Supabase CLI** | Levanta Postgres+PostGIS+Auth locales y aplica migraciones (`supabase start`, `db push`). Misma versión que el CI (`3.1.0`, ver `.github/workflows/ci.yml`). |
| **Python 3.10+** | El venv del backend y el ETL (`make venv`). |
| **`psql` / `pg_dump` (libpq)** | Seeds, `make backup`, `make restore-test`. |
| **JDK 17** | Lo exige Gradle/Android. |
| **Flutter (canal stable)** | La app. |
| **Android SDK (command-line tools)** | Compilar el APK. No hace falta Android Studio. |
| **`flyctl`** | Desplegar a Fly.io (`docs/06-deploy.md`). |
| **`adb`** (en `platform-tools`) | Instalar el APK por cable. |

## 2. Instalación

```bash
# Herramientas base
brew install git gh openjdk@17 libpq python@3.12 supabase/tap/supabase flyctl
brew install --cask docker android-commandlinetools
brew install --cask flutter            # o seguí https://docs.flutter.dev/get-started/install
brew link --force libpq                # psql y pg_dump en el PATH
```

Variables de entorno (agregalas a `~/.zshrc` y abrí una terminal nueva):

```bash
export JAVA_HOME=/opt/homebrew/opt/openjdk@17
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"
```

SDK de Android y Flutter (aceptá las licencias cuando las pida; los números exactos de versión son
los que pide el Flutter de turno: si `flutter doctor` o Gradle piden otros, instalá esos):

```bash
yes | sdkmanager --licenses
sdkmanager "platform-tools" "platforms;android-35" "platforms;android-36" \
  "build-tools;35.0.0" "build-tools;28.0.3" "ndk;28.2.13676358"
flutter config --jdk-dir "$JAVA_HOME" --android-sdk "$ANDROID_HOME"
flutter doctor            # Xcode en rojo es esperable: iOS está fuera de alcance
```

(Emulador opcional: `docs/03`, «Armar el entorno desde cero», pasos 5 y siguientes. Para
probar de verdad la cámara y el GPS conviene un celular real.)

Repo y cuentas:

```bash
gh auth login
gh repo clone crulises/almacenero && cd almacenero
fly auth login                 # abre el navegador; después: fly auth whoami
supabase login                 # solo si vas a tocar el proyecto remoto
```

## 3. Lo que NO viaja con el repo (copialo a mano, por un canal seguro)

| Qué | Dónde vive | Notas |
|-----|-----------|-------|
| **Keystore** (`.jks`) y `app/android/key.properties` | Tu gestor de contraseñas / backup | Sin esto no podés publicar actualizaciones. `docs/06-deploy.md` §2. Guardala **fuera** del repo y ajustá `storeFile`. |
| `.env` local | Se crea solo con `make up` (copia `.env.example`) | No hay nada que migrar. |
| `.env.prod` | Tu gestor de contraseñas | Credenciales de Supabase de producción. |
| Secretos de Fly | Ya están guardados en Fly | No hay que moverlos: `fly secrets list -a <app>` muestra los nombres. |
| Backups (`backups/*.dump`) | Donde los hayas copiado | La carpeta está ignorada por git. |
| Datos del ETL (`etl/data/`) | No hace falta copiarlos | Se vuelven a bajar con `make etl-*-descargar`. |
| Contador de versión de `make apk` | `.git/almacenero-apk-version` | Es local; si falta empieza de nuevo (solo afecta el número de debug). |

## 4. Verificar que quedó bien

```bash
make up          # Supabase local + backend + panel; termina mostrando http://localhost:8080/admin/
curl localhost:8000/v1/health          # {"status":"ok","version":"dev"}
make test        # backend (pytest contra el Postgres local), ETL y tests de Flutter
make lint        # ruff + flutter analyze
make apk         # APK debug para el celular (misma red Wi-Fi)  → app/build/app/outputs/flutter-apk/app-debug.apk
make version     # versión del pubspec, git describe y qué responde producción
fly auth whoami  # con la cuenta de Fly correcta
```

Para probar el release firmado: poner `key.properties` y `make apk-release` (`docs/06-deploy.md` §2).

## 5. Si algo falla

- Docker no alcanza memoria / `port is already allocated`: `docs/03`.
- `flutter doctor` pide otra versión de SDK/NDK: instalá la que pide.
- Gradle se cuelga bajando el NDK: `docs/03`, «Gradle se cuelga bajando el NDK».
- Después de actualizar Flutter: `cd app && flutter clean && flutter pub get`.
