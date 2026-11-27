# Cuentas ligables (corte 21) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ligar la cuenta anónima a Google conservando el mismo `usuarios.id`, abrir sesión con una cuenta ya ligada, y que el admin reclame huérfanas.

**Architecture:** El backend hace de proxy fino de GoTrue (`POST /token?grant_type=id_token`, con `link_identity` para ligar) con dos endpoints nuevos bajo `/v1/auth/google/`. Las cuentas nuevas creadas por Google pasan por las mismas defensas que el alta anónima. El reclamo de huérfanas es una transacción del panel con estado nuevo `fusionada`. La app usa Google Sign-In nativo y solo habla con el backend.

**Tech Stack:** FastAPI + asyncpg + pytest (Postgres real, GoTrue simulado con `httpx.MockTransport` como en `backend/tests/test_auth_proxy.py`), migraciones SQL planas en `supabase/migrations/`, Flutter (`google_sign_in`, `shared_preferences`), panel `admin-web/` (Alpine, HTML/JS estático).

**Spec:** `docs/superpowers/specs/2026-11-26-cuentas-ligables-design.md` (leerlo entero; los «Llamados del agente» son parte del diseño). Spike: GoTrue v2.197.0.

## Global Constraints

- Mismo `usuarios.id` al ligar; el alias **no** cambia; karma e historial intactos.
- Solo Google, solo Android; scopes `openid email profile`. **Sin** contraseña/email como método, **sin** Apple/iOS, **sin** sexo/fecha de nacimiento/país.
- Se guarda **solo el email**; nombre y foto de Google no se persisten. El email lo ve solo el admin en el panel: **ningún** endpoint de usuarios comunes lo devuelve (ni `GET /v1/me`).
- Lógica de negocio en FastAPI; integridad en Postgres (constraints/triggers); migraciones SQL planas portables; el cliente Flutter habla solo con el backend.
- Códigos de error: `google_ya_ligado` (409), `ya_ligada` (409), `invitacion_requerida` / `invitacion_invalida` / `alta_cerrada` (403, ya existentes), `cuenta_baja` (403), `cuenta_fusionada` (403).
- `config.karma_umbral_ligar_cuenta` default **3**, editable en el panel. «Luego» oculta la tarjeta **7 días** (guardado en el celular).
- Reclamar: motivo obligatorio de 3 a 300 caracteres; auditoría `usuario.reclamar`; solo huérfana **anónima y activa** → cuenta **ligada y activa**; estado `fusionada` (no `baja`).
- Textos en español rioplatense. UTC en la base, hora local solo al mostrar.
- Trailer de commits: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Un PR a `main`, **sin mergear**.

## Review Focus

1. **Cancelar el selector de Google o sin red** no deja la app en estado raro ni gasta nada → test de app (`ligarConGoogle` con servicio que devuelve `null`).
2. **Doble toque en «Ligar»** no manda dos pedidos → test de app (llamadas simultáneas comparten operación).
3. **`id_token` vencido o inválido** → 401 claro, nunca un 500 → test de backend (Task 2).
4. **`/entrar` con cuenta de baja y un PIN en el cuerpo** no gasta el PIN → test de backend (Task 3).
5. **Reclamar** dos veces, a sí misma, una huérfana ya fusionada o una cuenta de baja → 409/422 sin tocar datos → tests de backend (Task 5).
6. **`/ligar` con una cuenta ya ligada** → 409 `ya_ligada` → test de backend (Task 2).

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `supabase/migrations/20261204000001_cuentas_ligables.sql` (nuevo) | estado `fusionada`, `fusionada_en`, clave de config |
| `backend/app/auth.py` (modificar) | `Usuario.es_anonimo`, `asegurar_usuario`, 403 `cuenta_fusionada` |
| `backend/app/api/v1/auth.py` (modificar) | `/auth/google/ligar` y `/auth/google/entrar`, mapeo del 422, `/refresh` y `cuenta_fusionada` |
| `backend/app/api/v1/me.py` (modificar) | `ligada`, `sugerir_ligar` |
| `backend/app/services/reclamos.py` (nuevo) | transacción de reclamo |
| `backend/app/api/v1/admin/usuarios.py` (modificar) | `POST /usuarios/{id}/reclamar`, `ligada` y `email` en la ficha |
| `admin-web/public/{index.html,app.js}` (modificar) | ficha: estado ligada, email, botón Reclamar |
| `app/lib/data/google_signin_service.dart` (nuevo) | selector nativo de Google |
| `app/lib/data/auth_repository.dart`, `user_repository.dart` (modificar) | ligar/entrar; `ligada`, `sugerirLigar` |
| `app/lib/data/aviso_ligar.dart` (nuevo) | «Luego» por 7 días |
| `app/lib/ui/{home_screen,acerca_screen,invitacion_screen}.dart` (modificar), `ui/tarjeta_ligar.dart` (nuevo) | tarjeta, «Cuenta», «Entrar con Google» |
| `supabase/config.toml`, `.env.example`, `Makefile` | Google activado, linking manual, `--dart-define` |
| docs 01, 02, 03, 04-plan-v0.2, CLAUDE.md | al día |

---

### Task 1: Migración, estado `fusionada` y umbral en config

**Files:**
- Create: `supabase/migrations/20261204000001_cuentas_ligables.sql`
- Modify: `backend/app/services/config.py` (DEFAULTS)
- Test: `backend/tests/test_integridad.py` (agregar), `backend/tests/test_api.py` si hay test de config

**Interfaces:**
- Produces: `usuarios.estado in ('activo','baja','fusionada')`, `usuarios.fusionada_en uuid null references usuarios(id)`; `config.DEFAULTS["karma_umbral_ligar_cuenta"] = 3`.

- [ ] **Step 1: Test que falla** — `test_estado_fusionada_requiere_destino`: con `app.estado_write = on`, `update usuarios set estado='fusionada'` sin `fusionada_en` viola un check; con `fusionada_en` distinto de `id` pasa; sin `app.estado_write` el trigger existente `proteger_estado` lo rechaza. `test_karma_umbral_ligar_default_3`: `config.leer(pool, "karma_umbral_ligar_cuenta") == 3`.
- [ ] **Step 2: Correr** `make test` (o `cd backend && pytest tests/test_integridad.py -k fusionada -v`). Esperado: FAIL.
- [ ] **Step 3: Migración.** Reemplazar el check de `estado` por `('activo','baja','fusionada')`; agregar `fusionada_en`; `check ((estado = 'fusionada') = (fusionada_en is not null) and fusionada_en is distinct from id)`. Mantener `check ((estado='baja') = (baja_at is not null))`. `proteger_estado` ya cubre cualquier estado ≠ `activo`; verificar que no hay que tocarlo. Agregar `DEFAULTS["karma_umbral_ligar_cuenta"] = 3` y, si la lista de claves editables del panel es explícita (`backend/app/api/v1/admin/config.py`), sumarla con descripción.
- [ ] **Step 4: Aplicar y correr** `make migrate && make test`. Esperado: PASS.
- [ ] **Step 5: Commit** `feat(db): estado fusionada y umbral para ligar cuenta`.

---

### Task 2: `POST /v1/auth/google/ligar`

**Files:**
- Modify: `backend/app/auth.py`, `backend/app/api/v1/auth.py`
- Test: `backend/tests/test_auth_google.py` (nuevo; fixture `proveedor` copiada del patrón de `test_auth_proxy.py`)

**Interfaces:**
- Consumes: `current_user`, `bearer`, `_pedir_sesion`, `_auth_id_de` de `auth.py`.
- Produces:
  - `Usuario.es_anonimo: bool = True` (se lee de `usuarios.es_anonimo` en `current_user`).
  - `async def asegurar_usuario(conn, auth_id: UUID, email: str | None, es_anonimo: bool) -> asyncpg.Record` en `app/auth.py` (el upsert actual de `current_user` extraído tal cual; `current_user` lo usa).
  - `class GoogleIn(BaseModel): id_token: str (max_length 4096); nonce: str | None; codigo_invitacion: str | None`.
  - `async def _pedir_sesion_google(http, id_token, nonce, bearer: str | None) -> Sesion`: `POST {auth_url}/token?grant_type=id_token` con `{"provider":"google","id_token":…,"nonce":…,"link_identity": bearer is not None}` y header `Authorization: Bearer` si hay. 422 con `error_code == "identity_already_exists"` → `HTTPException(409, detail={"codigo":"google_ya_ligado","mensaje":…})`; 400/401/403/422 restantes → 401 «sesión inválida» (token de Google vencido o inválido).
  - `POST /auth/google/ligar` → `Sesion`.

- [ ] **Step 1: Tests que fallan:** (a) `test_ligar_ok`: anónima (token de `make_token`) manda `id_token`; el simulado devuelve sesión con un access token cuyos claims traen `email` y `is_anonymous=false`; se espera 200, request al proveedor con `link_identity: true` y `Authorization: Bearer` del usuario, y en la base `usuarios.email` cargado, `es_anonimo = false`, **mismo `id` y `alias`**. (b) `test_ligar_google_ya_ligado_409`: proveedor 422 `identity_already_exists` → 409 y `detail.codigo == "google_ya_ligado"`, la fila no cambia. (c) `test_ligar_id_token_invalido_401`: proveedor 400 → 401. (d) `test_ligar_cuenta_ya_ligada_409`: usuario con `es_anonimo = false` → 409 `ya_ligada` y **no** se llama al proveedor. (e) `test_ligar_sin_token_401`.
- [ ] **Step 2: Correr** `pytest backend/tests/test_auth_google.py -v`. Esperado: FAIL.
- [ ] **Step 3: Implementar** lo de Interfaces. El email sale de los claims del `access_token` devuelto (`jwt.decode(..., verify_signature=False)`, como `_auth_id_de`); `update usuarios set email=$2, es_anonimo=false where id=$1`. Registrar el dispositivo (`X-Device-Id`) como en `/refresh`.
- [ ] **Step 4: Correr** el archivo y `make test`. Esperado: PASS.
- [ ] **Step 5: Commit** `feat(auth): ligar la cuenta anónima a Google`.

---

### Task 3: `POST /v1/auth/google/entrar` con defensas

**Files:**
- Modify: `backend/app/api/v1/auth.py`, `backend/app/auth.py` (403 `cuenta_fusionada`)
- Test: `backend/tests/test_auth_google.py`

**Interfaces:**
- Consumes: `_pedir_sesion_google` (con `bearer=None`), `asegurar_usuario`, `dispositivos.tiene_baja/registrar`, `invitaciones.consumir/devolver/anotar_usuario`, `config.leer`, `limitar`.
- Produces: `POST /auth/google/entrar` (cuerpo `GoogleIn`) → `Sesion`; constante `CUENTA_FUSIONADA` en `app/auth.py` (`codigo: cuenta_fusionada`, «esta cuenta se unió a otra: entrá con Google»).

Regla (spec «Defensas» y llamados 1–2): tras recibir la sesión del proveedor, si **hay** fila en `usuarios` para ese `auth_id` es una cuenta conocida: `baja` → 403 `cuenta_baja`, `fusionada` → 403 `cuenta_fusionada`, si no, registrar dispositivo y devolver la sesión **sin PIN**. Si **no** hay fila es nueva: rechazar si el dispositivo tiene una cuenta de baja (403 `cuenta_baja`); aplicar `modo_acceso` (`abierto` pasa; `solo_invitacion` exige `codigo_invitacion`: falta → 403 `invitacion_requerida`, inválido → 403 `invitacion_invalida`; `alta_manual` → 403 `alta_cerrada`); si pasa, `asegurar_usuario(..., es_anonimo=False)`, `invitaciones.anotar_usuario`, registrar dispositivo. El PIN solo se consume si la cuenta es nueva y el chequeo de dispositivo ya pasó; se devuelve (`invitaciones.devolver`) si algo falla después. Mismo rate limit que `/anonymous` con clave `google:{ip}`.

- [ ] **Step 1: Tests que fallan** (proveedor simulado con un access token cuyo `sub` es un uuid nuevo o uno ya insertado en `usuarios`): conocida ligada → 200 sin PIN y dispositivo registrado; conocida de baja → 403 `cuenta_baja` aunque venga un PIN, y **el PIN sigue disponible** (Review Focus 4); conocida `fusionada` → 403 `cuenta_fusionada`; nueva con `modo_acceso = abierto` → 200 y se crea la fila con `es_anonimo = false` y email; nueva con `solo_invitacion` sin PIN → 403 `invitacion_requerida` y **no** se crea fila; nueva con PIN válido → 200, PIN usado y anotado; nueva con dispositivo de una cuenta de baja → 403 `cuenta_baja` y PIN sin gastar; nueva con `alta_manual` → 403 `alta_cerrada`; `id_token` vencido (proveedor 400) → 401 (Review Focus 3).
- [ ] **Step 2: Correr** y ver FAIL.
- [ ] **Step 3: Implementar** según la regla de arriba. En `current_user` y `/refresh`, `estado == 'fusionada'` → 403 `CUENTA_FUSIONADA` (mismo lugar donde hoy se corta `baja`).
- [ ] **Step 4: Correr** `make test`. Esperado: PASS.
- [ ] **Step 5: Commit** `feat(auth): entrar con Google con las defensas del alta`.

---

### Task 4: `GET /v1/me` con `ligada` y `sugerir_ligar`

**Files:**
- Modify: `backend/app/api/v1/me.py`
- Test: `backend/tests/test_api.py` o `test_auth.py` (donde estén los tests de `/me`)

**Interfaces:**
- Produces: `MeOut.ligada: bool` (`not es_anonimo`), `MeOut.sugerir_ligar: bool` (`es_anonimo and karma >= config.karma_umbral_ligar_cuenta`). **No** se agrega el email.

- [ ] **Step 1: Tests que fallan:** anónima con karma 2 → `sugerir_ligar` false; con karma 3 → true; con `config_temporal("karma_umbral_ligar_cuenta","5")` y karma 3 → false; cuenta ligada con karma 10 → `sugerir_ligar` false y `ligada` true; la respuesta **no** contiene `email`.
- [ ] **Step 2: Correr** y ver FAIL. **Step 3: Implementar.** **Step 4: Correr** `make test`.
- [ ] **Step 5: Commit** `feat(me): ligada y sugerir_ligar`.

---

### Task 5: Reclamar huérfanas (servicio y endpoint de admin)

**Files:**
- Create: `backend/app/services/reclamos.py`
- Modify: `backend/app/api/v1/admin/usuarios.py`, `backend/app/services/permisos.py` (capacidad `usuario.reclamar`, solo admin, como `usuario.dar_baja`)
- Test: `backend/tests/test_reclamos.py` (nuevo)

**Interfaces:**
- Produces:
  - `class ReclamoInvalido(Exception): codigo: str; mensaje: str; http: int`.
  - `async def reclamar(pool, admin: Usuario, huerfana_id: UUID, destino_id: UUID, motivo: str) -> int` (devuelve la cantidad de filas que **no** pudieron pasar por unicidad). Una transacción: valida (misma persona no, huérfana `es_anonimo` y `activo`, destino `not es_anonimo` y `activo`: si no, `ReclamoInvalido` 409 o 422 si es la misma), suma karma con `set_config('app.karma_write','on',true)`, reasigna `user_id`/`usuario_id` en `precios`, `validaciones` (si choca `unique (precio_id, user_id)` se deja la fila en la huérfana y se cuenta), sugerencias y avisos del catálogo (**verificar los nombres reales con** `grep -rn "references usuarios" supabase/migrations`; no tocar `eventos` ni `auditoria_admin`), pone la huérfana en `fusionada`/`fusionada_en = destino_id` con `app.estado_write = on`, y escribe auditoría `usuario.reclamar` con el motivo (usar `services/auditoria.py` como `_cambiar_estado`).
  - `POST /v1/admin/usuarios/{destino_id}/reclamar`, cuerpo `{huerfana_id: UUID, motivo: str (3–300)}` → `{"filas_sin_pasar": int}`.
  - La ficha (`UsuarioDetalle`) suma `ligada: bool`, `email: str | None` y, en «otras cuentas del dispositivo», `ligada` y `estado` de cada una.

- [ ] **Step 1: Tests que fallan:** reclamo feliz (karma sumado, precios reasignados, huérfana `fusionada` con `fusionada_en`, auditoría con motivo, la cuenta ligada conserva alias); sin motivo → 422; mismo usuario → 422; huérfana ya `fusionada` → 409 y nada cambia; destino anónimo → 409; destino de baja → 409; huérfana ligada → 409; conflicto de unicidad en `validaciones` → reclamo ok con `filas_sin_pasar == 1`; no admin → 403; karma negativo de la huérfana resta (Review Focus 5).
- [ ] **Step 2: Correr** y ver FAIL. **Step 3: Implementar.** **Step 4: Correr** `make test`.
- [ ] **Step 5: Commit** `feat(admin): reclamar huérfanas`.

---

### Task 6: Panel web — ficha y botón «Reclamar»

**Files:** Modify `admin-web/public/index.html`, `admin-web/public/app.js`.

**Interfaces:** Consumes `GET /v1/admin/usuarios/{id}` (`ligada`, `email`, otras cuentas) y `POST …/reclamar` de la Task 5.

- [ ] **Step 1:** En la ficha del usuario mostrar «Cuenta ligada a Google» o «Anónima» y el email (solo si existe). En «Otras cuentas en el mismo dispositivo» mostrar el estado de cada una y, si la ficha abierta es una cuenta **ligada** y la otra es anónima y activa, un botón «Reclamar» que abre un diálogo con el motivo (obligatorio, 3–300) y confirma. Mostrar `filas_sin_pasar` si es mayor que 0. Estado `fusionada` con etiqueta propia y link al destino.
- [ ] **Step 2:** Verificar a mano con `make admin-web` (descripción en el PR) y que `make lint` pase. Si el panel tiene tests, agregarlos.
- [ ] **Step 3: Commit** `feat(admin-web): ficha con cuenta ligada y reclamo`.

---

### Task 7: Config de GoTrue, `.env.example`, Makefile

**Files:** Modify `supabase/config.toml`, `.env.example`, `Makefile`.

- [ ] **Step 1:** `[auth.external.google]`: `enabled = true`; en `[auth]`: `enable_manual_linking = true`. `.env.example`: descomentar `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` con la aclaración **sin comentarios en la misma línea**. En el target `apk` del Makefile agregar `--dart-define=GOOGLE_WEB_CLIENT_ID=$(GOOGLE_CLIENT_ID)` (leído del `.env`, sin imprimirlo).
- [ ] **Step 2:** Reiniciar el stack (`make down && make up`) y comprobar `curl localhost:54321/auth/v1/settings` → `external.google: true`. Si el `id_token` nativo trae nonce, no tocar `skip_nonce_check`; si no se puede, activarlo y anotar el costo en el Doc 3 (llamado 6).
- [ ] **Step 3: Commit** `chore: activar Google y linking manual en GoTrue local`.

---

### Task 8: App — servicio de Google, `AuthRepository`, `UserRepository`

**Files:**
- Create: `app/lib/data/google_signin_service.dart`, `app/lib/data/aviso_ligar.dart`
- Modify: `app/pubspec.yaml` (`google_sign_in`), `app/lib/data/auth_repository.dart`, `app/lib/data/user_repository.dart`, `app/lib/app_deps.dart`
- Test: `app/test/auth_repository_test.dart`, `app/test/user_repository_test.dart`, `app/test/aviso_ligar_test.dart` (nuevo)

**Interfaces:**
- Produces:
  - `abstract class GoogleSignInService { Future<String?> obtenerIdToken(); }` — `null` si la persona cancela. Implementación real con `serverClientId: String.fromEnvironment('GOOGLE_WEB_CLIENT_ID')`.
  - `AuthRepository({…, GoogleSignInService? google})`; `Future<void> ligarConGoogle()` (POST `/auth/google/ligar`; guarda la sesión nueva); `Future<void> entrarConGoogle({String? codigoInvitacion})` (POST `/auth/google/entrar`; guarda la sesión; sin token propio previo). Excepciones: `GoogleCancelado`, `GoogleYaLigado` (409 `google_ya_ligado`), `InvitacionRequerida` (reusar la existente, también para `entrarConGoogle`), `CuentaBaja`/el manejo actual de 403.
  - `Me.ligada: bool`, `Me.sugerirLigar: bool` (JSON `ligada`, `sugerir_ligar`).
  - `class AvisoLigar { AvisoLigar(SharedPreferences, {DateTime Function()? now}); bool estaOculto(); Future<void> ocultarSieteDias(); }`.

- [ ] **Step 1: Tests que fallan:** ligar ok guarda la sesión nueva y no pide token a Google si el servicio devuelve `null` (lanza `GoogleCancelado` y **no** llama al backend); dos llamadas simultáneas a `ligarConGoogle` comparten una sola operación (Review Focus 1 y 2); 409 `google_ya_ligado` → `GoogleYaLigado`; `entrarConGoogle` con 403 `invitacion_requerida` → `InvitacionRequerida` y con el PIN reintenta; `Me.fromJson` lee `ligada` y `sugerir_ligar` (default false); `AvisoLigar` oculta 7 días y vuelve a mostrar al día 8.
- [ ] **Step 2: Correr** `cd app && flutter test`. Esperado: FAIL.
- [ ] **Step 3: Implementar** según Interfaces; patrón de operación compartida igual que `_inFlight` de `accessToken`.
- [ ] **Step 4: Correr** `flutter test && flutter analyze`. Esperado: PASS.
- [ ] **Step 5: Commit** `feat(app): ligar y entrar con Google en el repositorio`.

---

### Task 9: App — tarjeta, «Cuenta» en Acerca de y «Entrar con Google»

**Files:**
- Create: `app/lib/ui/tarjeta_ligar.dart`
- Modify: `app/lib/ui/home_screen.dart`, `app/lib/ui/acerca_screen.dart`, `app/lib/ui/invitacion_screen.dart`
- Test: `app/test/tarjeta_ligar_test.dart` (widget), `app/test/invitacion_integracion_test.dart` (ampliar)

**Interfaces:** Consumes `Me.sugerirLigar`, `Me.ligada`, `AvisoLigar`, `AuthRepository.ligarConGoogle/entrarConGoogle`.

Textos fijos: tarjeta «Protegé tu cuenta» / «Ligala a Google para no perder tu karma si cambiás de celular.» con botones «Ligar» y «Luego»; en Acerca de, ítem «Cuenta» con «Cuenta anónima» o «Ligada a Google» y la acción «Ligar a Google» si no está ligada; en la pantalla del PIN, «¿Ya tenés cuenta?» y «Entrar con Google». Errores: cancelado (sin mensaje de error, solo vuelve), sin red, «Ese Google ya tiene una cuenta: ¿querés entrar con ella?» (acción «Entrar con esa cuenta»), cuenta de baja (pantalla existente). Si la cuenta es nueva y pide invitación: «No encontramos tu cuenta: si sos nuevo, ingresá tu código».

- [ ] **Step 1: Tests que fallan:** la tarjeta se ve solo con `sugerirLigar` y no oculta; «Luego» la oculta; «Ligar» llama `ligarConGoogle`, refresca `/me` y desaparece; con `GoogleYaLigado` ofrece «Entrar con esa cuenta»; en Acerca de, «Cuenta» muestra el estado; en la pantalla del PIN «Entrar con Google» abre el flujo y, ante `InvitacionRequerida`, pide el código.
- [ ] **Step 2: Correr** y ver FAIL. **Step 3: Implementar.** **Step 4: Correr** `flutter test && flutter analyze && make lint`.
- [ ] **Step 5: Commit** `feat(app): tarjeta Protegé tu cuenta, Cuenta y Entrar con Google`.

---

### Task 10: Docs, verificación final y PR

**Files:** Modify `docs/04-plan-v0.2.md` (parte A: decisiones y estado), `docs/01-producto-vision.md` («Identidad»: ligar con Google, reclamo por admin), `docs/02-spec-tecnico.md` (endpoints, estado `fusionada`, nonce), `docs/03-problemas-soluciones.md` (cliente Web vs Android, `.env` sin comentarios inline, `identity_already_exists`, 422→409), `CLAUDE.md` (mención del corte 21 y docs).

- [ ] **Step 1:** Escribir las secciones. **Step 2:** `make lint && make test` (todo en verde) y `cd app && flutter test && flutter analyze`. **Step 3:** Probar en el celular (`make apk`) y anotar los pasos en el PR: ligar con una cuenta con karma ≥ 3, reinstalar y «Entrar con Google», reclamar una huérfana desde el panel.
- [ ] **Step 4:** `git push -u origin feat/cuentas-ligables` y `gh pr create --base main` con cuerpo en español (qué se probó, pasos a mano, que el spike corrió con GoTrue v2.197.0) terminando con `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. **No mergear.**

## Autorrevisión
- **Cobertura del spec:** ligar (T2), entrar y defensas (T3), huérfanas y reclamo (T5, T6), tarjeta/Acerca de/PIN (T8, T9), `/me` (T4), privacidad (Global Constraints + test sin `email` en T4), config y pasos del dueño (T7), docs (T10), umbral configurable (T1, T4).
- **Consistencia de nombres:** `asegurar_usuario`, `_pedir_sesion_google`, `GoogleIn`, `Usuario.es_anonimo`, `CUENTA_FUSIONADA`, `reclamar`, `ReclamoInvalido`, `ligarConGoogle`, `entrarConGoogle`, `GoogleCancelado`, `GoogleYaLigado`, `AvisoLigar`, `Me.ligada`/`sugerirLigar` se usan igual en todas las tareas.
