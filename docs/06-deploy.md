# Doc 6 — Release y deploy (corte 10)

Guía paso a paso para sacar Almacenero a internet: firmar el APK, desplegar el backend y el
panel en Fly.io, conectar el dominio en Cloudflare y la base en Supabase. Está escrita para
aprender el **porqué** de cada pieza, no solo copiar comandos.

Contexto y decisiones: `docs/04-plan-v0.0.2.md` (§7 y «Decisiones» 7-12). Armar la máquina
de desarrollo: `docs/00-setup-entorno.md`. Problemas ya vividos: `docs/03-problemas-soluciones.md`.

> **Regla de esta guía:** los pasos marcados 👤 los hacés vos (crean cosas, gastan plata o
> exponen algo). Nada de esto se corre desde CI ni se automatiza solo.

## 0. El mapa: qué es cada pieza

```
 Celular (APK firmado) ──HTTPS──▶ almacenero-api.crulises.dev ──▶ Fly.io (backend FastAPI) ──▶ Supabase
                                       (Cloudflare: DNS + proxy)                              (Postgres + Auth)
 Navegador (admin)     ──HTTPS──▶ almacenero.crulises.dev/admin ─▶ Fly.io (nginx estático)
                                                                    └─ el JS del panel llama al backend de arriba
```

| Pieza | Qué hace | Por qué está ahí |
|-------|----------|------------------|
| **Supabase cloud** | Postgres (+PostGIS) y Auth (GoTrue) | Es la base de verdad. El backend es la única puerta de entrada. |
| **Fly.io** | Corre nuestros contenedores Docker | Supabase no corre código nuestro: el backend FastAPI necesita un host de contenedores. |
| **Cloudflare** | DNS (y opcionalmente proxy/protección) del dominio `crulises.dev` | Los nombres lindos apuntan a Fly; podés cambiar de host sin tocar el APK. |
| **Docker** | Empaqueta la app con todo lo que necesita | La misma imagen corre en tu Mac y en Fly: «en mi máquina anda» deja de ser excusa. |
| **Keystore** | La identidad criptográfica de tu app Android | Android solo deja actualizar una app si la firma la misma clave (§2). |

Costo estimado total: **menos de 1 USD por mes** con el uso del grupo (detalle en §4).

### Checklist en orden (resumen de lo que te toca)

1. 👤 Supabase: crear el proyecto, aplicar migraciones, copiar credenciales (§5.1).
2. 👤 Fly: `fly apps create` de las dos apps, cargar secretos, `make deploy-api` y `make deploy-web` (§5.2-5.4).
3. 👤 Cloudflare: CNAME en nube gris → `fly certs add` → nube naranja + SSL Full (strict) (§5.5).
4. 👤 `make admin-crear` contra producción y probar el panel (§5.6).
5. 👤 Poner `key.properties`, hacer el tag `v0.1.0` y `make apk-release` (§2 y §8).
6. 👤 Simulacro de restauración (§7) y, recién ahí, repartir el APK.

---

## 1. Qué cambió en este corte (para no sorprenderse)

- **`applicationId` = `dev.crulises.almacenero`** (antes `ar.almacenero.almacenero`). Android lo
  trata como **otra app**: hay que **desinstalar la versión vieja** en cada celular de prueba;
  se pierde la sesión guardada (el usuario anónimo se recrea).
- El release **exige HTTPS**: el permiso de HTTP sin cifrar existe solo en el manifest de debug.
- El panel ahora vive bajo `/admin/`: en local es `http://localhost:8080/admin/` (la raíz
  redirige).

---

## 2. Firma del APK release (Android)

### Qué es una keystore y por qué importa

Un APK tiene que estar **firmado**. La firma no es un candado de seguridad para los usuarios:
es la **identidad del autor**. Cuando instalás una actualización encima de una app, Android
compara la firma de la versión instalada con la del APK nuevo: **si no coincide, se niega a
actualizar**. Por eso:

- La **keystore** (`.jks`/`.keystore`) es el archivo con tu clave privada. Se genera **una
  sola vez** y se usa para todas las versiones de la app, para siempre.
- Tiene dos contraseñas: la de la *store* (el archivo) y la de la *key* (la clave dentro, con un
  **alias**). Las dos las elegís vos.
- **Si la perdés** (o perdés la contraseña): no hay forma de recuperarla. Las apps ya
  instaladas no pueden actualizarse; hay que firmar con una clave nueva, y cada usuario tiene
  que **desinstalar e instalar de nuevo** (con pérdida de la sesión guardada). Con ~50 amigos es un
  fastidio, no una catástrofe, pero se evita con un backup (más abajo). Distinto es en Play
  Store, donde Google puede guardar la clave de subida (*Play App Signing*): acá no usamos Play.
- **Nunca** va al repositorio, ni a un chat, ni se envía por mail sin cifrar. El repo es
  público: `.gitignore` ya ignora `key.properties`, `*.jks` y `*.keystore`.

### Crear la keystore (solo si no tuvieras una)

Ya tenés una generada; esta sección queda para otra máquina o si algún día hay que rehacerla.
`keytool` viene con el JDK 17:

```bash
keytool -genkeypair -v -storetype PKCS12 -keystore ~/almacenero-release.jks \
  -alias almacenero -keyalg RSA -keysize 2048 -validity 10000
```

Te pide las contraseñas y datos del certificado (nombre, etc.; son opcionales en la práctica).
`-validity 10000` son ~27 años: el certificado no debe vencer antes que la app.

### Usar la keystore que ya tenés

1. Ubicá el archivo `.jks` (guardalo **fuera** del repo, p. ej. `~/.android-keys/`). Tené a mano
   las dos contraseñas y el alias. Para recordar el alias y verificar que es la correcta
   (te pide la contraseña de la store por teclado; no se imprime):

   ```bash
   keytool -list -v -keystore /ruta/a/tu.jks | grep -E "Alias|SHA256|Valid"
   ```

2. Creá `app/android/key.properties` (**ignorado por git**) con este formato:

   ```properties
   storeFile=/ruta/absoluta/a/tu.jks
   storePassword=<contraseña de la store>
   keyAlias=<alias>
   keyPassword=<contraseña de la key>
   ```

   `storeFile` puede ser absoluta (recomendado) o relativa a `app/android/`. Verificá que git no
   lo ve: `git status` no debe mostrarlo.

3. Cómo lo usa Gradle: `app/android/app/build.gradle.kts` lee `key.properties`, define un
   `signingConfig` «release» y lo aplica al build release. Si el archivo no existe, el build
   **falla con un mensaje claro**: a propósito, para que nunca salga un «release» firmado por
   accidente con la clave de debug (esa clave la puede generar cualquiera).

### Backup de la keystore

Una copia en **dos lugares fuera de la máquina** (p. ej. gestor de contraseñas con adjuntos +
un pendrive o bucket privado cifrado), junto con las contraseñas y el alias (en el gestor de
contraseñas, **no** en el mismo lugar sin cifrar). Probá cada tanto que la copia abre
(`keytool -list`). Anotá también la huella SHA-256 del certificado: sirve para comprobar que un
APK está firmado con *tu* clave (`apksigner verify --print-certs app.apk`, en
`$ANDROID_HOME/build-tools/<versión>/`).

### Generar el APK

```bash
make apk-release                       # contra https://almacenero-api.crulises.dev
make apk-release API_URL_PROD=https://otra-api.ejemplo.com   # otra URL
make apk-release API_TIMEOUT_S=40     # (opcional) timeout por intento
```

Qué hace: toma la versión del `pubspec.yaml` (`0.1.0+1` → `0.1.0`), usa la cantidad de commits como
`versionCode` (siempre crece, y sale igual en cualquier máquina), compila solo para arm64
(todos los celulares actuales) e imprime el SHA-256 del archivo final: `dist/almacenero-0.1.0.apk`
(carpeta ignorada por git). Avisa si no estás parado en el tag de esa versión o si hay cambios
sin commitear (§8). La URL de la API queda grabada en el APK: por eso conviene el dominio propio,
que permite cambiar de host sin recompilar.

### Instalar y repartir

- Por cable: `adb install -r dist/almacenero-0.1.0.apk` (`-r` actualiza conservando datos).
- Al grupo: mandar el archivo por el medio que usen (chat, Drive, un release de GitHub **privado**).
  Cada persona tiene que habilitar «instalar apps de orígenes desconocidos» para el navegador o app
  desde la que lo abre, y puede aparecer el aviso de **Play Protect** («app no verificada»):
  «Instalar de todas formas».
- La primera instalación de `dev.crulises.almacenero` pide desinstalar la versión vieja (§1).
- Las actualizaciones se instalan **encima** y solo funcionan si: (a) la firma es la misma y (b) el
  `versionCode` es mayor. Ambas cosas las cuida `make apk-release`.
- Play Store no hace falta ahora (cuenta de pago único y requisitos de prueba cerrada); evaluarlo si
  el grupo crece.

---

## 3. Docker en producción: qué cambia respecto del desarrollo

Docker empaqueta la app y sus dependencias en una **imagen**; un **contenedor** es esa imagen
corriendo. Fly toma tu `Dockerfile`, construye la imagen y la ejecuta en una máquina virtual
mínima (*Machine*) en su región.

**Backend (`backend/Dockerfile`)** — la misma imagen sirve en local y en Fly:

| Decisión | Por qué |
|----------|---------|
| Usuario no root (`almacenero`, uid 10001) | Si alguien explotara una falla de la app, no sería dueño del contenedor. |
| Sin `--reload` | La recarga automática es para desarrollar; en prod gasta recursos y es un riesgo. |
| Escucha en `$PORT` | Las plataformas eligen el puerto: la imagen respeta la variable (`8000` por defecto, `8080` en Fly). |
| `HEALTHCHECK` con `python -c` | La imagen `slim` no trae `curl`; consulta `/v1/health`, que prueba la conexión a la base. |
| `ARG APP_VERSION` | La versión del tag queda en la imagen y se ve en `/v1/health` y `/docs`: sabés qué está corriendo. |
| Config solo por variables de entorno | Nada de secretos en la imagen: se inyectan al arrancar (`fly secrets`, `fly.toml [env]`). |

**Panel (`admin-web/Dockerfile`)** — `nginxinc/nginx-unprivileged` (nginx que corre sin root,
puerto 8080) sirviendo los archivos estáticos bajo `/admin/`. La URL del backend no está en el código: nginx escribe
`/admin/config.js` al arrancar con la variable `API_URL` (la plantilla es `admin-web/nginx.conf.template`;
la imagen oficial reemplaza `${API_URL}` al iniciar). Sin `API_URL` (desarrollo) el panel usa «mismo
host, puerto 8000», así que `make up` sigue funcionando y también desde otra máquina de la red.
Los redirects son relativos (`absolute_redirect off`): detrás de Fly nginx no sabe su nombre ni el
`https` público, y si armara la URL absoluta saldría con `:8080` y `http`.

**CORS:** el navegador solo deja que `almacenero.crulises.dev` llame a `almacenero-api.crulises.dev` si
el backend lo autoriza: `CORS_ORIGINS` en `backend/fly.toml`. La app móvil no usa CORS.

Probar las imágenes de producción en tu máquina, sin Fly (no gasta nada):

```bash
docker build --build-arg APP_VERSION=0.0.0-test -t almacenero-api backend
docker run --rm -p 9000:9000 -e PORT=9000 -e DATABASE_URL=postgresql://postgres:postgres@host.docker.internal:54322/postgres almacenero-api
curl localhost:9000/v1/health      # {"status":"ok","version":"0.0.0-test"}
```

---

## 4. Costos y opciones de hosting (precios verificados el 2026-11-21)

Los precios cambian: revisalos en <https://docs.fly.io/about/pricing> antes de decidir.

### Fly.io (elegida, para backend y panel)

| Concepto | Precio | Qué significa para nosotros |
|----------|--------|-----------------------------|
| Máquina `shared-cpu-1x` 256 MB | 2,19 USD/mes si corriera 24/7 (por segundo; precio de iad/ewr, otras regiones varían) | Con `auto_stop_machines` solo se paga el tiempo despierta: unas pocas horas al mes ≈ centavos. |
| 512 MB | 3,69 USD/mes 24/7 | Solo si el backend se queda sin memoria. |
| Máquina **detenida** | 0,15 USD/GB-mes del rootfs (la imagen) | Una imagen de ~200 MB parada cuesta ~0,03 USD/mes. |
| IPv4 compartida / IPv6 | Gratis | **No** pedir IPv4 dedicada (2 USD/mes). |
| Certificados TLS | Los primeros 10 de la organización gratis | Usamos 2. |
| Salida de datos | 0,04 USD/GB en Sudamérica (entrada gratis) | Un grupo de 50 amigos queda muy por debajo de 1 GB/mes. |
| Volúmenes | 0,15 USD/GB-mes | **No usamos** (la base está en Supabase). |
| Cuota mínima / gratuidad | Sin cargo fijo mensual; la página dice que una factura mensual menor a 5 USD se **perdona** | Confirmar en <https://docs.fly.io/about/free-waiver> que sigue vigente. |
| Prueba | La página indica 1 USD de crédito por 7 días para organizaciones nuevas; tu cuenta mostró créditos propios: mirá el saldo real en el panel de Fly | Después hace falta tarjeta cargada. |

**Estimación realista:** backend y panel despiertos ~20 h/mes cada uno → ~0,10 USD de cómputo +
~0,06 USD de discos parados + centavos de salida de datos = **≈ 0,2-0,5 USD/mes**, normalmente
por debajo del umbral de perdón.

La región `gru` (São Paulo) es la más cercana a Argentina y a Supabase `sa-east-1`. El precio de
cómputo en `gru` no aparece en la página de forma estática: mirá `fly platform regions` y el panel de
costos tras el primer día. Para el volumen de este proyecto no cambia la conclusión.

### Alternativa para el panel: Cloudflare Pages

| | Fly (nginx) | Cloudflare Pages |
|---|---|---|
| Costo | ~0,05 USD/mes (disco parado + minutos despierto) | 0: estáticos sin límite de requests ni ancho de banda; 500 builds/mes, 20.000 archivos, 25 MiB por archivo |
| Arranque | 1-3 s si estaba dormido | Sin arranque en frío (CDN) |
| Herramientas | Las mismas que el backend (`fly`) | Otro CLI (`wrangler`) o conectar el repo de GitHub |
| Rutas bajo `almacenero.crulises.dev` | `/admin` hoy; otra ruta = otra app + enrutar | El dominio entero apunta a un proyecto de Pages: servís `/admin/` como carpeta; otras rutas, en el mismo sitio o con un Worker |
| URL del API | Variable `API_URL` al arrancar | Hay que generar `admin/config.js` al publicar |

**Decisión:** empezar con **Fly para los dos**: un solo CLI, un solo flujo de deploy y la diferencia
de costo son centavos mientras los créditos cubren todo. Si el costo importara o el arranque en frío
del panel molestara, el panel es lo primero que se mueve a Pages (es estático): se publica
`admin-web/public` bajo `admin/` más un `admin/config.js` con
`window.API_URL = "https://almacenero-api.crulises.dev";`, y se cambia el DNS. El backend **no** cabe en
Pages (es un servidor Python). Otras opciones para el backend, comparadas en `docs/04` §7: Render
gratis (gratis, sin tarjeta, pero arranque de 30-60 s); Railway (sin escala a cero real).

### Supabase

| | Free | Pro |
|---|---|---|
| Precio | 0 | desde 25 USD/mes |
| Base | 500 MB, CPU compartida | 8 GB incluidos |
| Salida de datos | 5 GB/mes | 250 GB |
| Usuarios activos | 50.000 | 100.000 |
| Pausa por inactividad | **Sí: tras 1 semana sin actividad** | Nunca |
| Backups automáticos | **No** (por eso `make backup`) | 7 días |

500 MB alcanzan para el grupo y SEPA de un día, no para un catálogo mundial completo de Open Food
Facts (docs/04 §4). La pausa y la falta de backups son los costos ocultos del plan gratis (§6 y §7).

### Cloudflare

DNS y proxy en el plan gratis. El dominio se pagó al costo del registro. **Cloudflare Access**
(login delante de `/admin`): hay un plan gratis de Zero Trust, pero **no pude verificar el límite de
usuarios vigente**; confirmalo en el panel antes de contar con él.

---

## 5. Paso a paso: del repo a producción

> `flyctl` ya está instalado y logueado en tu máquina (`fly auth whoami`). Cada comando `fly …`
> sobre una app va con `-a <app>` o desde la carpeta que tiene el `fly.toml`.

### 5.1 Supabase (👤)

1. Crear el proyecto en <https://supabase.com/dashboard>: región **South America (São Paulo)**,
   guardar la contraseña de la base en tu gestor de contraseñas (la vas a necesitar).
2. **Migraciones** (SQL plano, antes de desplegar el backend). Con el CLI, enlazado al proyecto:

   ```bash
   supabase login
   supabase link --project-ref <REF>      # <REF> está en la URL del dashboard y en Settings → General
   supabase db push                       # aplica supabase/migrations/* a la base remota
   ```

   `db push` muestra qué va a aplicar y pide confirmación. Las migraciones crean las extensiones
   (`postgis`, `pg_trgm`, `unaccent`) con `create extension if not exists`. **No** corras
   `supabase/demo.sql`.
3. **Config inicial.** `supabase/seed.sql` es idempotente pero inserta un «Local del admin» de ejemplo
   en Buenos Aires: para producción conviene correr solo la parte de `config` o borrar/renombrar ese
   local desde el panel después.
4. **Credenciales** (Dashboard → botón *Connect* y *Settings → API*):
   - **`DATABASE_URL`: el *session pooler*** (puerto **5432**), con la forma
     `postgresql://postgres.<REF>:<PASSWORD>@aws-<N>-sa-east-1.pooler.supabase.com:5432/postgres`.
     El host exacto lo da el diálogo *Connect* (el `<N>` no se puede adivinar). Si la contraseña
     tiene caracteres como `@ # ? &`, codificalos en porcentaje.
   - **`AUTH_URL`** = `https://<REF>.supabase.co/auth/v1`
   - **`JWKS_URL`** = `https://<REF>.supabase.co/auth/v1/.well-known/jwks.json` (probalo con `curl`:
     tiene que devolver un JSON con `keys`).
   - **`AUTH_API_KEY`** = la clave *publishable/anon* (Settings → API). **No** la `service_role`.
5. En *Authentication → Providers*: Email habilitado con «Confirm email» **apagado** si querés que
   `make admin-crear` y el panel funcionen sin correo, y *Anonymous sign-ins* **encendido** (la app
   arranca con auth anónima).

**¿Por qué el session pooler (5432) y no la conexión directa o el modo transacción (6543)?**

- La conexión **directa** (`db.<REF>.supabase.co`) en el plan gratis es solo **IPv6**; Fly sale por
  IPv4/IPv6 según el caso y no conviene depender de eso. El pooler compartido es IPv4.
- El **modo transacción** (6543) comparte conexiones entre clientes y **no soporta *prepared
  statements***; `asyncpg` (nuestro driver) los usa por defecto, así que rompe de forma
  intermitente. El **modo sesión** (5432) sí los soporta. Es la opción sin tocar código.
- Nuestro pool pide hasta 10 conexiones (`db.py`); el pooler gratis tiene un tope de clientes: con
  una sola máquina sobra.

### 5.2 Crear las apps en Fly (👤: crea recursos en tu cuenta)

```bash
fly apps create almacenero-api      # si el nombre está tomado: elegir otro y cambiarlo en backend/fly.toml (y CNAME)
fly apps create almacenero-web
```

Crear una app **no cuesta nada**: es un registro. Las máquinas aparecen en el primer `deploy`.

### 5.3 Secretos y variables

Qué va dónde:

| Dónde | Qué | Por qué |
|-------|-----|---------|
| `fly secrets` | `DATABASE_URL`, `AUTH_URL`, `AUTH_API_KEY`, `JWKS_URL` | Datos del proyecto o con contraseña: se guardan cifrados en Fly, nunca en git. |
| `backend/fly.toml [env]` | `PORT`, `LOG_LEVEL`, `CORS_ORIGINS`, `PROXY_HOPS` | No son secretos y conviene que estén versionados. |
| `admin-web/fly.toml [env]` | `API_URL` | Idem. |
| Imagen | `APP_VERSION` | Se inyecta al construir (`make deploy-api`). |

Cargar los secretos **sin que queden en el historial de la terminal** (los tipeás en el prompt):

```bash
read -rs "DB?DATABASE_URL: "; echo
read -rs "KEY?AUTH_API_KEY: "; echo
fly secrets set -a almacenero-api --stage \
  DATABASE_URL="$DB" AUTH_API_KEY="$KEY" \
  AUTH_URL="https://<REF>.supabase.co/auth/v1" \
  JWKS_URL="https://<REF>.supabase.co/auth/v1/.well-known/jwks.json"
unset DB KEY
```

(En bash, `read -rsp "DATABASE_URL: " DB`). `--stage` guarda los secretos sin reiniciar nada: se
aplican en el primer deploy. `fly secrets list -a almacenero-api` muestra los nombres (nunca los valores).

### 5.4 Primer deploy (👤: construye y ejecuta máquinas → cuesta centavos)

```bash
git checkout v0.1.0            # o la rama/tag que quieras publicar (§8)
make deploy-api                # backend: construye la imagen en Fly con APP_VERSION y la lanza
make deploy-web                # panel
fly status -a almacenero-api   # estado de la máquina
fly logs -a almacenero-api     # logs en vivo
curl https://almacenero-api.fly.dev/v1/health   # {"status":"ok","version":"0.1.0"}
```

(`make deploy-api` = `cd backend && fly deploy --build-arg APP_VERSION=<pubspec>`.) El primer
`fly deploy` asigna a la app una IPv4 **compartida** (gratis); comprobá con `fly ips list -a
almacenero-api` que no dice «dedicated»: si dijera, `fly ips release <ip>` evita el cargo de 2 USD.

Probar el **escala a cero**: pasados unos minutos sin tráfico, `fly machine list -a almacenero-api`
muestra la máquina `stopped`; el primer `curl` la despierta (unos segundos). La app muestra
«Despertando servidor…» y reintenta (ajuste previo al corte 10).

### 5.5 Dominio en Cloudflare (👤)

El orden importa. Fly necesita **verificar que el dominio es tuyo** y emitir el certificado
(Let's Encrypt); si el proxy naranja de Cloudflare ya estuviera delante, esa verificación puede
fallar. Por eso: **primero DNS puro (nube gris), después el proxy**.

1. **CNAME en modo «solo DNS»** (nube **gris**): en Cloudflare → DNS → Records:

   | Tipo | Nombre | Destino | Proxy |
   |------|--------|---------|-------|
   | CNAME | `almacenero-api` | `almacenero-api.fly.dev` | **Solo DNS (gris)** |
   | CNAME | `almacenero` | `almacenero-web.fly.dev` | **Solo DNS (gris)** |

2. **Pedir el certificado a Fly:**

   ```bash
   fly certs add almacenero-api.crulises.dev -a almacenero-api
   fly certs add almacenero.crulises.dev -a almacenero-web
   fly certs show almacenero-api.crulises.dev -a almacenero-api    # repetir hasta «Issued»
   ```

   `fly certs show` puede pedir además un registro `_acme-challenge` (CNAME): crealo también (gris);
   permite renovar el certificado aunque después actives el proxy.
3. Probar: `curl https://almacenero-api.crulises.dev/v1/health` y abrir
   `https://almacenero.crulises.dev/admin/`.
4. **Recién ahora, el proxy (nube naranja)** si lo querés (capa extra: WAF, rate limiting de
   Cloudflare, oculta el origen). Cloudflare → SSL/TLS → modo **Full (strict)**: Cloudflare le habla a
   Fly por HTTPS **validando** su certificado (los modos «Flexible» o «Full» sin strict dejan tramos sin
   cifrar o sin validar: no usarlos).
5. **Con el proxy naranja, la IP del cliente cambia de lugar.** El rate limit por IP (docs/04 §6) cuenta
   los proxies de la derecha del `X-Forwarded-For`: Fly es 1 y Cloudflare es otro. Por eso
   `PROXY_HOPS = "2"` en `backend/fly.toml` (con nube **gris** es `1`). Si el valor está mal el límite se
   degrada (todos parecen la misma IP, o se puede esquivar): ajustalo y `make deploy-api`. Verificación:
   en los logs, la IP registrada de tu celular tiene que ser la tuya, no una de Cloudflare ni de Fly.
6. *(Opcional)* **Cloudflare Access** para `/admin`: Zero Trust → Access → Applications → Self-hosted,
   dominio `almacenero.crulises.dev`, ruta `admin`, política «email = el tuyo». Protege **solo la
   página** del panel (HTML/JS); el API del panel sigue exigiendo rol admin por sí mismo. **Nunca**
   pongas Access delante de `almacenero-api…`: rompería la app del celular. Verificá primero los
   límites gratis vigentes.

> **Rutas futuras bajo `almacenero.crulises.dev`:** `/admin` ya es una app de Fly. Cuando haya otra ruta
> (`/estadisticas`, …) las opciones son: (a) un directorio más dentro del mismo nginx, si es estático;
> (b) otra app de Fly y un **Cloudflare Worker** que enrute por prefijo (requiere proxy naranja);
> (c) un subdominio propio. Decidirlo cuando llegue.

### 5.6 Crear el admin en producción (👤)

`make admin-crear` toma las variables de un archivo; usá uno aparte para producción (ignorado por git,
por el patrón `.env.*`):

```bash
cp .env.example .env.prod      # y completá: DATABASE_URL (session pooler), AUTH_URL, AUTH_API_KEY
make admin-crear EMAIL=vos@mail.com ENV_FILE=.env.prod
```

(Necesita `make venv` hecho. Acordate: `.env.prod` tiene la contraseña de la base: no lo
compartas ni lo subas.)

### 5.7 Rollback

Cada `fly deploy` crea una **release** con su imagen. Si la última salió mal:

```bash
fly releases -a almacenero-api          # historial: versión, estado, fecha
fly releases -a almacenero-api --image  # incluye la referencia de imagen de cada release
fly deploy -a almacenero-api --image registry.fly.io/almacenero-api:deployment-XXXX   # volver a esa imagen
```

O, más reproducible, redesplegar el **tag** de la versión anterior (la imagen se reconstruye igual):

```bash
git checkout v0.0.9 && make deploy-api    # y después `git checkout -` para volver a tu rama
```

Ojo: **las migraciones de la base no se deshacen** con un rollback del backend. Por eso las
migraciones deben ser compatibles hacia atrás (agregar columnas/tablas, no renombrar ni borrar en
el mismo release que cambia el código): así el código viejo sigue funcionando sobre el esquema nuevo.

### 5.8 Controlar el costo

- `fly apps list` y `fly machine list -a <app>`: solo debe haber **1 máquina** por app, y
  `stopped` cuando no hay tráfico.
- `fly ips list -a <app>`: sin IPs dedicadas. `fly volumes list -a <app>`: vacío.
- Panel de Fly → Billing: mirar el consumo de los primeros días y configurar el aviso de gasto.
- Para frenar todo: `fly scale count 0 -a almacenero-api` (apaga sin borrar) o
  `fly apps destroy <app>` (borra la app).

---

## 6. Supabase gratis: pausa y vigilancia

- El plan gratis **pausa el proyecto tras 1 semana sin actividad**. Un proyecto pausado no responde:
  el backend falla y la app muestra «no pudimos conectar». Se reactiva desde el dashboard («Restore» /
  «Unpause»; esta guía no lo pudo verificar paso a paso: seguí las instrucciones que muestra el
  dashboard) y vuelve con los datos (el plan gratis conserva el proyecto un tiempo limitado: ver
  condiciones vigentes en su página de precios).
- Con 50 personas usando la app a diario no se pausa. Para épocas muertas: abrir el panel o la app una
  vez por semana, o un cron en GitHub Actions que haga `curl https://almacenero-api.crulises.dev/v1/health`
  (despierta la máquina y consulta la base). *No está implementado: sumarlo si hiciera falta.*
- Si la pausa no es tolerable, la alternativa es Supabase Pro (25 USD/mes) u otro Postgres: el plan de
  escape (docs/04) deja el código sin acoplarse a Supabase.
- El plan gratis **no hace backups**: ver §7.

---

## 7. Backup y simulacro de restauración contra el Postgres real

`make backup` y `make restore-test` ya existen (docs/04, «Plan de escape»). Este es el procedimiento
para correrlos contra **producción**. Es **solo lectura** sobre la base real: `pg_dump` no modifica
nada, y la restauración de prueba va a una base **temporal local**.

> **Pendiente de tu OK:** este simulacro no se ejecutó contra la base real; lo corrés vos (o me lo
> pedís explícitamente cuando exista el proyecto de Supabase).

1. En `.env.prod` (§5.6) debe estar `DATABASE_URL`. Para el dump conviene la conexión por el
   **session pooler (5432)** (nunca el 6543).
2. Dump de producción:

   ```bash
   make backup ENV_FILE=.env.prod       # → backups/almacenero-<fecha>.dump + .conteos
   ```

   Verificá que los conteos impresos (locales, productos, precios, usuarios) son los de producción y no
   los de tu base local (si `.env.prod` no existe, el target usa `.env.example` y volcaría la base local).
   Requiere `pg_dump` de versión **igual o mayor** que el servidor (`brew install libpq`; hoy
   Supabase crea proyectos con Postgres 15-17).
3. Restaurar ese dump en la base **temporal local** (necesita `make up` corriendo):

   ```bash
   make restore-test                    # usa .env (la base local); restaura el último dump y compara conteos
   ```

   «Simulacro OK» = el dump de producción se restaura completo en un Postgres limpio. Si falla,
   anotá el error en `docs/03` (los filtros del Makefile ya cubren las diferencias conocidas entre
   versiones de `pg_dump`).
4. Copiá el `.dump` **fuera de la máquina** (otro disco o un bucket privado). Repetirlo antes de cada
   release y cada tanto (semanal mientras el plan sea gratis).
5. **Lo que el backup NO cubre:** `auth.users` de Supabase Auth (las cuentas y sus contraseñas) y los
   secretos. Los secretos viven en tu gestor de contraseñas; para Auth ver el plan de escape.

---

## 8. Versionado y ramas

### Un solo número para todo

La **versión de release** es `MAYOR.MENOR.PARCHE` (p. ej. `0.1.0`) y vive en **un lugar**:
`version:` de `app/pubspec.yaml` (la parte antes del `+`). De ahí salen todos los demás:

| Qué | De dónde sale |
|-----|---------------|
| App (`APP_VERSION`, `versionName`) | `make apk-release` la lee del pubspec |
| `versionCode` de Android | cantidad de commits (`git rev-list --count HEAD`) |
| Tag de git | `v0.1.0` en el commit del release |
| Backend en Fly | `make deploy-api` pasa la versión del pubspec como `APP_VERSION`; se ve en `/v1/health` |
| APK publicado | `dist/almacenero-0.1.0.apk` + su SHA-256 |

`make version` muestra la versión del pubspec, `git describe` y lo que responde producción.

Cuándo subir el número (SemVer pragmático para un proyecto chico): **PARCHE** = arreglos;
**MENOR** = funciones nuevas o cambios que obligan a actualizar la app (mientras estemos en `0.x`,
cualquier cambio incompatible entre app y backend sube el MENOR); **MAYOR** = `1.0.0` cuando
salga del grupo cerrado.

**Los builds de desarrollo** (`make apk`, debug) siguen con su contador local `serie.N` y el commit
(`app/tool/version.sh`): son pruebas, no releases. Con `version: 0.1.0+1` los debug salen
`0.1.0`, `0.1.1`… y el número **puede coincidir** con el de un release: lo que los distingue es el
commit y el `+local` que muestra la pantalla «Acerca de». Además, un debug va firmado con la clave
de debug y un release con tu keystore: Android no deja instalar uno encima del otro (hay que desinstalar).
Regla práctica: tras cada release, subí el `version:` del pubspec al siguiente MENOR/PARCHE para
que lo nuevo ya se llame distinto.

### Receta de un release

```bash
git switch main && git pull
# 1. Subir version: en app/pubspec.yaml (p. ej. 0.1.0+1) y comitear en una rama/PR «release».
make lint && make test
git tag -a v0.1.0 -m "v0.1.0"          # tag anotado, en el commit ya mergeado a main
git push origin v0.1.0
make deploy-api                         # backend (la imagen queda etiquetada con esa versión)
make deploy-web                         # panel, si cambió
make apk-release                        # APK firmado: dist/almacenero-0.1.0.apk
make backup ENV_FILE=.env.prod && make restore-test    # simulacro (§7)
make version                            # comprobar: pubspec = tag = backend en prod
```

Después, publicar el APK en un *GitHub Release* **privado** o por el medio que use el grupo, y
anotar el SHA-256. **Orden:** primero el backend (compatible hacia atrás con la app anterior), después
el APK; así los celulares viejos siguen andando mientras se actualizan.

### Ramas, PRs y merges

- `main` siempre está verde (CI) y es lo que se despliega. **Una rama por corte o tema**
  (`claude/<tema>`, `feat/…`, `docs/…`), un PR por rama a `main`.
- **Merge commit** (no squash): conserva los commits separados por tema; el historial
  cuenta la historia del corte.
- Commits chicos y temáticos, con trailer `Co-Authored-By`. Un PR = un tema revisable.
- Los tags `vX.Y.Z` se hacen **sobre `main`**, nunca sobre una rama de trabajo.
- Un arreglo urgente sobre una versión ya publicada: rama `hotfix/…` desde el tag, PR a `main`,
  tag nuevo de parche. Mientras no haya mantenimiento de versiones viejas, es lo mismo que una rama normal.

---

## 9. Qué se puede romper (guía rápida)

| Síntoma | Mirá |
|---------|------|
| La app dice «no pudimos conectar» | `curl https://almacenero-api.crulises.dev/v1/health`; `fly logs`; ¿Supabase pausado? (§6) |
| `fly deploy` falla en el build | `fly logs`, y probá la imagen en local (§3) |
| 502/525 con el proxy naranja | SSL en **Full (strict)** y certificado «Issued» en `fly certs show` |
| El panel carga pero «Failed to fetch» | `CORS_ORIGINS` no incluye el origen exacto (con `https://`, sin `/` final); `API_URL` del panel |
| `connection refused` / timeouts a la base | `DATABASE_URL` por el session pooler (5432); contraseña codificada |
| Errores de *prepared statement* | Estás usando el puerto 6543: pasá a 5432 |
| El APK no instala encima | Distinta firma (¿otra keystore?) o `versionCode` menor; o es el cambio de `applicationId` (§1) |

Más casos en `docs/03-problemas-soluciones.md`, sección «Release y deploy (corte 10)».
