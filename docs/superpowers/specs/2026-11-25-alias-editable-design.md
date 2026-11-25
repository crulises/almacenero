# Cambiar el alias — diseño

Estado: **propuesto por el agente, para que el dueño lo pruebe en el celular** (2026-11-25). Las
decisiones de la sección «Reglas» son del agente y se pueden retocar con `config` sin tocar código.
No choca con el Doc 1 (identidad: «el usuario arranca anónimo… al ligarse se atribuye a la persona
real») ni con el Doc 2 (el alias ya es columna de `usuarios`).

## Pedido del dueño
- Pantalla de inicio: lápiz a la derecha del alias; al tocarlo el alias se edita y al salir del
  campo se guarda en el servidor.
- Etapa 1: solo moderadores y admins; después se abre a `usuario` con un interruptor en `config`.
- Historial de alias de cada usuario (anterior, nuevo, instante UTC, quién lo cambió) en una tabla
  propia, visible en el detalle del usuario del panel.
- Que conviva con alta por email, asociar anónimo↔email y OAuth (Google/Apple): el alias es un
  atributo del **perfil** (`usuarios.id`), no de la identidad de GoTrue.

## Enfoques considerados
1. **Columna `usuarios.alias` + tabla de historial llenada por un trigger** (elegido). El alias sigue
   donde está (cero cambios en lo que ya lo lee: panel, dashboard, auditoría) y el historial lo
   garantiza Postgres (integridad), así ningún camino —app, panel, `make admin-crear`, el alta
   perezosa— puede cambiar el alias sin dejar rastro.
2. Solo `auditoria_admin`: no sirve, es para correcciones del admin, no guarda el alta ni los
   cambios del propio usuario y mezcla entidades.
3. Tabla de alias vigente separada (alias como entidad con vigencia): más puro para multi-identidad,
   pero obliga a tocar todas las consultas. Sobredimensionado para hoy.

## Modelo
- `usuarios_alias_historial` (append-only, como `auditoria_admin`): `id`, `usuario_id` (el id del perfil
  `usuarios.id`, **no** el `auth_id`; sin foreign key a propósito, como `eventos`: si se borra un perfil
  su rastro queda), `alias_anterior` (null en el alta), `alias_nuevo`, `cambiado_en`
  (`timestamptz`, default `now()`, UTC), `cambiado_por` (id de quien lo cambió; null = sistema/alta),
  `origen` (`alta | usuario | admin | sistema`).
- Trigger `AFTER INSERT OR UPDATE OF alias` en `usuarios`: escribe la fila. El backend le dice quién
  y por qué con `set_config('app.alias_actor', …)` / `('app.alias_origen', …)` dentro de su
  transacción (mismo patrón que karma/rol/estado). Sin esas variables queda `origen = 'sistema'`.
- Backfill: cada usuario existente recibe su fila de alta (`origen = 'alta'`, instante = `created_at`).
- Índice único parcial `lower(alias)` **excepto** los `anon-%`: los alias de alta se derivan de 6
  hex del `auth_id` y podrían colisionar; esos no cuentan como «tomados».
- Como el historial cuelga de `usuarios.id`, vincular el anónimo a un email o a Google/Apple no lo
  toca: si GoTrue conserva el usuario (lo normal al «linkear»), el perfil es el mismo; si algún día
  se fusionan dos perfiles, se reasignan las filas por `usuario_id`.

## Reglas (decididas por el agente)
| Tema | Decisión | Por qué |
|---|---|---|
| Largo | 3 a 24 caracteres (la base sigue admitiendo hasta 50 por los alias viejos) | Entra en pantalla y evita alias vacíos o kilométricos |
| Caracteres | Letras (con tildes/ñ), números, espacio, `.`, `_`, `-`; empieza y termina con letra/número; sin separadores seguidos. Se normaliza a NFC y se recortan espacios | Sin emojis ni caracteres invisibles ni de control |
| Unicidad | **Única sin distinguir mayúsculas** (`lower`) entre alias actuales; cambiar solo la capitalización del propio alias vale | Dos «Juan» confunden en rankings y moderación |
| Reservados | Prefijo `anon-` y las palabras `admin`, `administrador`, `moderador`, `mod`, `soporte`, `almacenero`, `sistema`, `staff`, `root` (también con sufijos tipo `admin2`: se compara la forma sin dígitos ni separadores) | Evita suplantar roles o volver a un alias de alta ajeno. Un admin editando desde el panel **no** está sujeto a reservados ni a lista de bloqueo |
| Ofensivos | `config.alias_bloqueados`: lista de fragmentos (sin tildes ni mayúsculas ni separadores; vacía por defecto). Además el admin puede corregir cualquier alias desde el panel y queda en el historial | Una lista fija inventada por mí sería arbitraria; la edita el dueño |
| Límite de cambios | `config.alias_max_cambios_por_dia` (3): se cuenta en el historial (`origen = 'usuario'`, últimas 24 h), como `max_precios_por_dia`. Admin exento. 429 `limite_alias` | Frena el «surf» de alias para evadir moderación; la tabla ya es la fuente de verdad |
| Alias anterior | **Se libera** (otra persona puede tomarlo); el historial conserva quién lo tuvo | Reservarlo para siempre agotaría nombres; la trazabilidad la da la tabla |
| Quién puede | `config.alias_editable_por_rol` (lista JSON, default `["moderador","admin"]`). Para abrirlo a todos: agregar `"usuario"`. Admin siempre puede. Un usuario restringido por karma no puede (escribe información) | El interruptor pedido |
| Cuentas de baja | Ya reciben 403 en cualquier endpoint | — |

## API
- `POST /v1/me/alias` `{alias}` → 200 `{alias}`; el cliente de la app solo tiene GET/POST, por eso POST.
  Errores con el formato de `reglas.py` (código, mensaje, cómo resolver): `alias_no_permitido` 403,
  `alias_invalido` 422, `alias_reservado` 422, `alias_en_uso` 409, `limite_alias` 429.
- `GET /v1/me` suma `puede_cambiar_alias` (la app decide con eso si muestra el lápiz).
- `PATCH /v1/admin/usuarios/{id}` (ya existía) pasa por el mismo servicio con `origen = 'admin'`.
- `GET /v1/admin/usuarios/{id}` suma `alias_historial` (más nuevo primero).

## App
En `HomeScreen`, junto al alias un `IconButton` de lápiz (solo con `puede_cambiar_alias`). Al tocarlo el
texto pasa a un `TextField` con foco; al perder el foco o confirmar se llama `deps.cambiarAlias`. Si
no cambió, no se manda. Si el servidor rechaza, se vuelve al alias anterior y se muestra el motivo.

## Fuera de alcance
Moderación automática con IA, alias visibles para otros usuarios (hoy solo los ve el panel), fusión de
perfiles.
