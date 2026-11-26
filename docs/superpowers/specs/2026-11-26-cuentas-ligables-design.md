# Cuentas ligables (corte 21, parte A del release 0.2.x) — diseño

Estado: **propuesto, pendiente de aprobación del dueño** (2026-11-26). Surge del brainstorming con el dueño;
lo que es decisión suya está marcado «(dueño)», lo que es llamado del agente, «(agente)». Ante una duda de
comportamiento gana el Doc 1 (Identidad); ante una duda técnica, el Doc 2. Principios en `docs/10-roadmap.md`.
Plan del release: `docs/04-plan-v0.2.md`.

## Intención y por qué
Hoy toda cuenta es anónima y no hay forma de abrir sesión con otra. Si se borran los datos de la app o se
reinstala, nace una cuenta nueva y la anterior queda **huérfana** con su karma e historial; el panel las muestra
en «Otras cuentas en el mismo dispositivo». El Doc 1 prevé ligar la cuenta anónima a email o Google («Google
primero»). Este corte entrega: **ligar la cuenta anónima a Google, abrir sesión con una cuenta ya ligada
(reinstalación u otro celular) y reclamar huérfanas desde el panel.**

## Objetivos
- Ligar una cuenta anónima a Google **conservando el mismo `usuarios.id`** (karma, alias, historial intactos).
- Abrir sesión con Google en un celular nuevo o tras reinstalar, volviendo a la misma cuenta.
- Que ligar o entrar con Google **no sirva para evadir** una baja, una restricción por karma ni el modo de acceso
  (PIN / invitación).
- Que el admin pueda **reclamar** una huérfana para una cuenta ligada, con motivo y auditoría.
- Privacidad: el email lo ve solo el admin en el panel; a otros usuarios solo se les muestra el alias.

## No-objetivos y anti-objetivos
- **No** contraseña ni email como método de ligado (dueño: «en otra sesión-corte»). Ese corte necesita SMTP real y
  un flujo de «olvidé mi contraseña»; no cambia este diseño (será otra forma de entrar a la misma cuenta).
- **No** Apple ID ni iOS (0.6; hará falta un cliente OAuth iOS de Google, uno solo por bundle ID).
- **No** pedir ni guardar sexo, fecha de nacimiento ni país (dueño: descartado; si se quiere, irá como formulario
  opcional del perfil en 0.3). Tampoco scopes sensibles de Google: solo `openid email profile`.
- **No** fusión automática de cuentas anónimas: no hay forma confiable de saber que dos son de la misma persona
  (el `ANDROID_ID` solo dice que pasaron por el mismo celular).
- **Anti-objetivo:** que «Entrar con Google» se vuelva una puerta de alta sin PIN, o una forma de volver tras una
  baja.

## Restricciones
- El cliente habla solo con el backend; el backend hace de proxy de GoTrue (como `/auth/anonymous` y `/refresh`).
- Lógica de negocio en FastAPI, integridad en Postgres, migraciones SQL planas; nada acoplado a Supabase por
  nombre salvo la capa de auth.
- Android únicamente. Nunca guardar secretos en el repo: `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` van en `.env`
  (ya referenciados por `supabase/config.toml`).
- El `applicationId` ya es `dev.crulises.almacenero` (PR #39).

## Lo verificado (spike, 2026-11-26, GoTrue v2.197.0)
Probado con un GoTrue descartable, el cliente Web real y un `id_token` real. Nota en la carpeta de notas de la sesión.
- `POST /token?grant_type=id_token` con `{"provider":"google","id_token":…,"link_identity":true}` y
  `Authorization: Bearer <token de la anónima>` → **mismo `auth_id`**, `is_anonymous` pasa a `false`, el usuario
  recibe el email. Requiere `GOTRUE_SECURITY_MANUAL_LINKING_ENABLED=true` (`enable_manual_linking` en `config.toml`).
- Google ya ligado a otra cuenta → **422 `identity_already_exists`**.
- Sin `link_identity` (otro celular) → devuelve la cuenta ya ligada, la misma. Si el Google no se conoce, GoTrue
  **crea una cuenta nueva** (de ahí la sección «Defensas»).
- Sin Bearer y con `link_identity` → error «Linking requires a valid user access token».

## Enfoques considerados
1. **Proxy fino de GoTrue en el backend** (elegido). Dos endpoints nuevos que reenvían el `id_token` y aplican las
   defensas del negocio. Consistente con lo que ya hay y con la regla «el cliente habla solo con el backend».
2. App directo contra GoTrue: rompe la regla de arquitectura y el backend no podría aplicar PIN, baja ni rate limit.
3. Backend valida el `id_token` y mantiene una tabla propia de identidades: duplica lo que GoTrue ya hace bien
   (unicidad, verificación) y no podemos emitir sesiones propias.

## Comportamiento

### Ligar (cuenta anónima → Google)
- La app obtiene el `id_token` con Google Sign-In nativo (cliente Web como `serverClientId`) y llama
  `POST /v1/auth/google/ligar` con su sesión anónima. El backend lo reenvía a GoTrue con `link_identity`.
- Éxito: la cuenta pasa a `es_anonimo = false` y guarda `email`; mismo `usuarios.id`; el alias **no cambia**.
- 422 (ese Google ya es de otra cuenta): el backend responde con un código propio (`google_ya_ligado`) y la app
  ofrece «Entrar con esa cuenta». La anónima actual se abandona (si está vacía no se pierde nada; si tenía cargas,
  queda huérfana y se puede reclamar desde el panel).

### Entrar (ya tengo cuenta)
- `POST /v1/auth/google/entrar` (sin sesión): reenvía a GoTrue sin `link_identity`.
- **Cuenta ya conocida y ligada:** devuelve la sesión sin pedir PIN. Antes de devolverla se mira el estado:
  `baja` → 403 `cuenta_baja` (igual que `/refresh`). La restricción por karma se sigue aplicando por request.
- **Cuenta que GoTrue acaba de crear** (Google desconocido): se tratan como un alta más (ver «Defensas»).
- Se registra el dispositivo (`X-Device-Id`) contra la cuenta, como en `/refresh`; así el panel ve las huérfanas del
  mismo celular.

### Defensas (que Google no abra una puerta)
Una cuenta **nueva** creada por Google pasa por las mismas defensas que `/auth/anonymous`: rate limit por IP,
`modo_acceso` (abierto / solo invitación / alta manual) y PIN o invitación, y el chequeo de dispositivo con una
cuenta dada de baja. Cuentas ya existentes no las necesitan. Un PIN no se gasta en vano si la cuenta resulta ser
conocida o el alta falla. Una cuenta de Google creada por GoTrue y rechazada por las defensas **nunca recibe
sesión** (el cliente solo obtiene tokens por el backend). (agente: cómo detectar «cuenta nueva» —por `usuarios`,
por los datos que devuelve GoTrue— lo resuelve quien implemente, con un test que lo cubra.)

### Huérfanas y reclamo
- Las huérfanas existentes y las que queden **no se fusionan solas** (dueño).
- Panel: la ficha de un usuario ya muestra «Otras cuentas en el mismo dispositivo»; suma el estado **ligada**
  (email visible solo para el admin) y la acción **Reclamar**: el admin elige una huérfana **anónima** y una cuenta
  **ligada**, escribe un motivo (obligatorio, 3–300 caracteres) y confirma.
- Efecto: el karma de la huérfana se **suma** a la cuenta ligada, la atribución de precios y demás cargas pasa a la
  cuenta ligada (el implementador lista las tablas con `usuarios.id`), y la huérfana queda en un estado nuevo
  **`fusionada`** (con a quién), que no puede iniciar sesión ni cargar. Todo en una transacción y con una fila de
  auditoría (`usuario.reclamar`). (agente: estado `fusionada` y no `baja`, porque `baja` marca el dispositivo y
  bloquearía altas legítimas en ese celular.)
- La persona **no** reclama desde la app (dueño: me cierra lo propuesto).
- No se puede reclamar una huérfana de baja ni una cuenta ligada de baja; el reclamo no levanta restricciones: el
  karma resultante decide el escalón, como siempre.

### Qué ve la app
- **Tarjeta «Protegé tu cuenta»** en el inicio: aparece cuando la cuenta es anónima y su karma llega a
  **`config.karma_umbral_ligar_cuenta`** (default **3**, configurable desde el panel; dueño). Texto no insistente:
  «Ligala a Google para no perder tu karma si cambiás de celular.» Botones **Ligar** y **Luego**; «Luego» la oculta
  7 días (agente: guardado en el celular, no en el servidor). Dueño: no hay otra UI nueva en el inicio.
- **Acerca de**: entrada permanente «Cuenta» con el estado (anónima / ligada a Google) y la acción de ligar.
- **Pantalla del PIN (primer arranque)**: «¿Ya tenés cuenta? Entrar con Google».
- El backend expone en `GET /v1/me` si corresponde sugerir (`sugerir_ligar`) y si la cuenta está ligada; la app no
  decide con reglas propias.
- Errores claros y sin tecnicismos (Google cancelado, sin red, `google_ya_ligado`, cuenta de baja).

### Privacidad
- Se guarda **solo el email** (y que está ligada a Google); el nombre y la foto de Google no se persisten (agente).
- El email aparece solo en el panel de admin. Ningún endpoint de usuarios comunes lo devuelve, ni siquiera el
  propio `GET /v1/me` (agente: si la app quiere mostrarlo, usa lo que le da Google en el dispositivo).
- Se menciona en la política de privacidad del release (0.6), junto con el `ANDROID_ID`.

### Interacción con `ANDROID_ID`, invitaciones y bajas (resumen)
| Caso | Resultado |
|---|---|
| Cuenta de baja intenta entrar con su Google | 403 `cuenta_baja`, sin sesión |
| Cuenta de baja crea otro Google nuevo en el mismo celular | Rechazada por el chequeo de dispositivo (como el alta anónima) |
| Alta nueva por Google con `modo_acceso = solo_invitacion` | Pide PIN; mismo trato que el alta anónima |
| Cuenta ligada restringida por karma | Sigue restringida (el escalón se deduce del karma) |
| Ligar la propia anónima | Mismo `usuarios.id`, karma y alias intactos |

## Pasos que no son código (dueño)
- `config.toml`: activar Google y `enable_manual_linking`. Local: `GOOGLE_CLIENT_ID/SECRET` en `.env`, **sin
  comentarios en la misma línea**.
- Google Cloud: cliente **Web** (hecho) y cliente **Android** con paquete `dev.crulises.almacenero` y el SHA-1 de
  cada keystore con la que se firme (debug y, cuando se use, release; el valor del cliente Android no va en ningún
  `.env`). Para el release de Play, el SHA-1 de la firma de Play. iOS: uno más, a futuro.
- Producción (0.6): mismas dos opciones en el proyecto de Supabase hosted.

## Llamados del agente tras la revisión del diseño (se pueden retocar)
1. **«Cuenta nueva» = sin fila en `usuarios`.** `/google/entrar` **crea** esa fila al aceptar la cuenta; por eso una
   cuenta de Google sin fila nunca recibió sesión de nuestra parte. Si las defensas la rechazan, queda un usuario
   huérfano en la base de GoTrue (sin sesión, sin uso): **se tolera**, no se borra (borrarlo exigiría la service key,
   que no queremos tener; ver docs/04 §9, decisión 4).
2. **PIN en `/google/entrar`:** el cuerpo lleva `codigo_invitacion` **opcional**. La app primero intenta sin PIN; si
   la cuenta es nueva y el modo exige invitación, el backend responde 403 `invitacion_requerida`, la app pide el PIN
   («No encontramos tu cuenta: si sos nuevo, ingresá tu código») y reintenta con el mismo `id_token`. El PIN se
   consume **solo** cuando la cuenta es nueva y el resto de las defensas pasó (y se devuelve si falla después).
3. **Reclamar:** solo entre una huérfana **anónima y activa** y una cuenta **ligada y activa**. El karma se suma
   (puede restar si la huérfana lo tenía negativo: lo decide el admin al elegir). Si al reasignar choca una
   restricción de unicidad, **se conserva la fila de la cuenta ligada** y la de la huérfana queda atribuida a la
   huérfana (se avisa cuántas filas quedaron sin pasar). La cuenta ligada conserva su alias.
4. **`/google/ligar`** escribe `email` y `es_anonimo = false` explícitamente (no depende del upsert perezoso de
   `current_user`) y **devuelve la sesión nueva**, que la app guarda: el JWT viejo todavía dice `is_anonymous = true`.
5. **422 de GoTrue:** se lee el cuerpo; `identity_already_exists` → **409** con `detail.codigo = google_ya_ligado`;
   cualquier otro error de GoTrue sigue el mapeo actual de `_pedir_sesion`.
6. **Nonce:** primero se intenta con nonce (Google Sign-In nativo lo permite). Solo si resultara imposible se
   activa `skip_nonce_check`, y se anota en el Doc 3 que el costo es que un `id_token` robado podría reutilizarse
   mientras no venza (≈1 h) y solo contra nuestro `client_id`, pasando por el backend.

## Qué queda a criterio de quien implemente
- Forma exacta de los endpoints y del resto de los códigos de error, siguiendo el estilo de `auth.py` y `me.py`.
- La lista de tablas a reasignar al reclamar; migración, tests contra Postgres real, textos del panel y de la app.
- Eventos de analítica (`cuenta_ligada`, `login_google`) si encajan con el corte 19b.

## Pendiente para otros cortes
- Contraseña / email como método (otra sesión; necesita SMTP).
- Apple ID e iOS (0.6). Perfil opcional con datos demográficos (0.3).
