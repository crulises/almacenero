"""Alias del usuario: reglas, permiso por rol y cambio con rastro.

El alias es un atributo del **perfil** (`usuarios.id`), no de la identidad del proveedor de auth.
El historial lo escribe un trigger de Postgres (`usuarios_alias_historial`); acá se decide quién
puede cambiarlo y qué alias se aceptan. Diseño en docs/superpowers/specs/ (alias-editable).
"""

import re
import unicodedata
from uuid import UUID

import asyncpg
from fastapi import HTTPException

from app.auth import Usuario
from app.services import config, permisos, reglas

LARGO_MIN = 3
LARGO_MAX = 24
_SEPARADORES = " ._-"

# Palabras que sugieren un rol o al sistema. Se comparan sin tildes, sin separadores y sin
# números al final («Admin2», «A.d.m.i.n» y «4dmin» cuentan como «admin»).
RESERVADAS = frozenset(
    {
        "admin",
        "administrador",
        "administradora",
        "moderador",
        "moderadora",
        "mod",
        "soporte",
        "almacenero",
        "sistema",
        "staff",
        "root",
    }
)
_LEET = str.maketrans("013457@$", "oieastas")


def normalizar(texto: str) -> str:
    """NFC y sin espacios en los bordes: «Jose» + tilde combinada queda «José»."""
    return unicodedata.normalize("NFC", texto).strip()


def error_de_formato(alias: str) -> str | None:
    """`alias_invalido` si el alias (ya normalizado) no cumple el formato; si no, None."""
    if not LARGO_MIN <= len(alias) <= LARGO_MAX:
        return "alias_invalido"
    if not (alias[0].isalnum() and alias[-1].isalnum()):
        return "alias_invalido"
    previo_separador = False
    for c in alias:
        if c.isalnum():
            previo_separador = False
        elif c in _SEPARADORES and not previo_separador:
            previo_separador = True
        else:  # emoji, control, invisible, o dos separadores seguidos
            return "alias_invalido"
    return None


def _sin_tildes(texto: str) -> str:
    d = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in d if not unicodedata.combining(c))


def _claves(alias: str) -> tuple[str, str]:
    """(solo letras y números, lo mismo con 0→o, 1→i, 3→e…): para reservados y bloqueados."""
    plano = "".join(c for c in _sin_tildes(alias) if c.isalnum())
    return plano, plano.translate(_LEET)


def es_reservado(alias: str) -> bool:
    if alias.casefold().startswith("anon-"):
        return True
    plano, leet = _claves(alias)
    return any(re.sub(r"\d+$", "", c) in RESERVADAS for c in (plano, leet)) or leet in RESERVADAS


def esta_bloqueado(alias: str, fragmentos: list[str]) -> bool:
    plano, leet = _claves(alias)
    for f in fragmentos:
        clave = "".join(c for c in _sin_tildes(str(f)) if c.isalnum())
        if clave and (clave in plano or clave in leet):
            return True
    return False


async def _error(pool, codigo: str, **extra) -> HTTPException:
    regla = reglas.REGLAS[codigo]
    return HTTPException(
        regla.status, detail=reglas.detalle(regla, await reglas.mensajes(pool), **extra)
    )


async def roles_habilitados(conn: asyncpg.Pool | asyncpg.Connection) -> set[str]:
    valor = await config.leer(conn, "alias_editable_por_rol")
    roles = {str(r) for r in valor} if isinstance(valor, list) else set()
    return roles | {"admin"}  # un admin nunca queda afuera por un valor mal escrito


async def puede_cambiar(conn: asyncpg.Pool | asyncpg.Connection, user: Usuario) -> bool:
    """Lo que la app usa para mostrar el lápiz: el rol está habilitado en `config`."""
    return user.rol in await roles_habilitados(conn)


async def cambiar_propio(pool: asyncpg.Pool, user: Usuario, pedido: str) -> str:
    """El usuario cambia su propio alias. Devuelve el alias guardado."""
    if not await puede_cambiar(pool, user):
        raise await _error(pool, "alias_no_permitido")
    permisos.exigir_carga(user)  # restringido por karma: no escribe
    alias = normalizar(pedido)
    if error := error_de_formato(alias):
        raise await _error(pool, error, minimo=LARGO_MIN, maximo=LARGO_MAX)
    if es_reservado(alias):
        raise await _error(pool, "alias_reservado")
    if esta_bloqueado(alias, list(await config.leer(pool, "alias_bloqueados") or [])):
        raise await _error(pool, "alias_bloqueado")
    async with pool.acquire() as conn, conn.transaction():
        # Serializa los cambios del mismo usuario (dos pedidos a la vez no esquivan el tope).
        actual = await conn.fetchval("select alias from usuarios where id = $1 for update", user.id)
        if actual == alias:
            return alias
        if user.rol != "admin":
            maximo = int(await config.leer(conn, "alias_max_cambios_por_dia"))
            hechos = await conn.fetchval(
                "select count(*) from usuarios_alias_historial where cambiado_por = $1 "
                "and origen = 'usuario' and cambiado_en > now() - interval '1 day'",
                user.id,
            )
            if hechos >= maximo:
                raise await _error(pool, "limite_alias", maximo=maximo)
        await _guardar(conn, pool, user.id, alias, actor=user.id, origen="usuario")
    return alias


async def cambiar_por_admin(
    conn: asyncpg.Connection, pool: asyncpg.Pool, usuario_id: UUID, pedido: str, admin_id: UUID
) -> tuple[str, str]:
    """Un admin corrige el alias de otra persona (dentro de la transacción del llamador).
    No lo frenan reservados, lista de bloqueo ni tope; sí el formato y la unicidad.
    Devuelve (alias_anterior, alias_nuevo)."""
    alias = normalizar(pedido)
    if error := error_de_formato(alias):
        raise await _error(pool, error, minimo=LARGO_MIN, maximo=LARGO_MAX)
    antes = await conn.fetchval("select alias from usuarios where id = $1 for update", usuario_id)
    if antes is None:
        raise HTTPException(404, "usuario no encontrado")
    if antes != alias:
        await _guardar(conn, pool, usuario_id, alias, actor=admin_id, origen="admin")
    return antes, alias


async def _guardar(
    conn: asyncpg.Connection,
    pool: asyncpg.Pool,
    usuario_id: UUID,
    alias: str,
    *,
    actor: UUID,
    origen: str,
) -> None:
    """UPDATE con el autor y el origen para el trigger del historial."""
    await conn.execute("select set_config('app.alias_actor', $1, true)", str(actor))
    await conn.execute("select set_config('app.alias_origen', $1, true)", origen)
    try:
        # Un savepoint: si la base rechaza por duplicado, la transacción sigue usable.
        async with conn.transaction():
            await conn.execute("update usuarios set alias = $2 where id = $1", usuario_id, alias)
    except asyncpg.UniqueViolationError as e:
        raise await _error(pool, "alias_en_uso") from e


async def historial(conn: asyncpg.Pool | asyncpg.Connection, usuario_id: UUID) -> list[dict]:
    """Todos los alias que tuvo, del más nuevo al más viejo."""
    rows = await conn.fetch(
        """
        select h.id, h.alias_anterior, h.alias_nuevo, h.cambiado_en, h.origen,
               h.cambiado_por as cambiado_por_id, u.alias as cambiado_por_alias
        from usuarios_alias_historial h
        left join usuarios u on u.id = h.cambiado_por
        where h.usuario_id = $1
        order by h.cambiado_en desc, h.id desc
        """,
        usuario_id,
    )
    return [dict(r) for r in rows]
