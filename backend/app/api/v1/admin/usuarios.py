from datetime import datetime
from decimal import Decimal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.v1.admin.auditoria import AuditoriaOut, historial
from app.api.v1.admin.consulta import Consulta, escapar_like
from app.api.v1.admin.paginas import Pagina
from app.auth import Usuario
from app.db import get_pool
from app.services import alias as servicio_alias
from app.services import auditoria, dispositivos, moderacion, reclamos
from app.services.permisos import exigir

router = APIRouter(tags=["admin"])

_ORDEN = {
    "alta": "u.created_at desc",
    "karma": "u.karma desc, u.created_at desc",
    "cargas": "cargas desc, u.created_at desc",
}


class UsuarioAdminOut(BaseModel):
    id: UUID
    auth_id: UUID
    alias: str
    email: str | None
    es_anonimo: bool
    anonimo_auth_id: UUID | None  # el id anónimo con el que empezó (asociación)
    rol: str
    karma: int
    # Moderación (docs/04 §9): el estado se guarda; el escalón se deduce del karma.
    estado: str  # activo | baja | fusionada
    baja_at: datetime | None
    fusionada_en: UUID | None = None  # corte 21: a qué cuenta ligada se unió (estado fusionada)
    escalon: str  # normal | aviso | restringido
    cargas: int
    locales_creados: int
    created_at: datetime
    # Con qué invitación entró (rastro para no volver a invitar a quien se dio de baja).
    # Con el código compartido solo queda el último que lo usó; los PINs son exactos.
    invitacion_codigo: str | None = None
    invitacion_nota: str | None = None


class CargaOut(BaseModel):
    id: UUID
    precio: Decimal
    fecha: datetime
    local_nombre: str
    ean: str | None
    producto_nombre: str | None


class LocalCreadoOut(BaseModel):
    id: UUID
    nombre: str
    verificado: bool
    fuente: str


class CuentaHermanaOut(BaseModel):
    id: UUID
    alias: str
    estado: str  # activo | baja | fusionada
    es_anonimo: bool  # false: ya está ligada a Google; true: puede ser una huérfana


class AliasHistorialOut(BaseModel):
    id: UUID
    alias_anterior: str | None  # None: es el alias con el que nació la cuenta
    alias_nuevo: str
    cambiado_en: datetime  # UTC
    origen: str  # alta | usuario | admin | sistema
    cambiado_por_id: UUID | None
    cambiado_por_alias: str | None


class UsuarioDetalle(UsuarioAdminOut):
    """La ficha del usuario: identidad, actividad y cambios anteriores."""

    cargas_recientes: list[CargaOut]
    locales_creados_lista: list[LocalCreadoOut]
    historial: list[AuditoriaOut]
    # Otras cuentas que usaron el mismo dispositivo (ANDROID_ID, docs/04 §9).
    mismo_dispositivo: list[CuentaHermanaOut] = []
    # Todos los alias que tuvo (más nuevo primero), con quién y cuándo los cambió.
    alias_historial: list[AliasHistorialOut] = []


class RolIn(BaseModel):
    rol: str = Field(pattern="^(usuario|moderador|admin)$")
    motivo: str | None = Field(default=None, max_length=300)


class KarmaIn(BaseModel):
    delta: int = Field(ge=-1000, le=1000)
    motivo: str = Field(min_length=3, max_length=300)


class BajaIn(BaseModel):
    motivo: str = Field(min_length=3, max_length=300)


class ReclamoIn(BaseModel):
    huerfana_id: UUID
    motivo: str = Field(min_length=3, max_length=300)


class ReclamoOut(BaseModel):
    # Filas que no pasaron por chocar con una restricción de unicidad: quedan con la huérfana.
    filas_sin_pasar: int


class UsuarioPatch(BaseModel):
    alias: str = Field(min_length=1, max_length=200)


_SELECT = """
    select u.id, u.auth_id, u.alias, u.email, u.es_anonimo, u.anonimo_auth_id, u.rol,
           u.karma, u.created_at, u.estado, u.baja_at, u.fusionada_en,
           (select i.codigo from invitaciones i where i.usada_por_auth = u.auth_id
             limit 1) as invitacion_codigo,
           (select i.nota from invitaciones i where i.usada_por_auth = u.auth_id
             limit 1) as invitacion_nota,
           (select count(*) from precios p where p.user_id = u.id) as cargas,
           (select count(*) from locales l where l.creado_por = u.id) as locales_creados
    from usuarios u
"""


async def _salida(pool: asyncpg.Pool | asyncpg.Connection, row) -> UsuarioAdminOut:
    d = dict(row)
    d["escalon"] = await moderacion.escalon_de(pool, d["karma"], d["rol"])
    return UsuarioAdminOut(**d)


@router.get("/usuarios", response_model=Pagina[UsuarioAdminOut])
async def listar_usuarios(
    tipo: str | None = Query(None, pattern="^(anonimo|registrado)$"),
    rol: str | None = Query(None, pattern="^(usuario|moderador|admin)$"),
    estado: str | None = Query(None, pattern="^(activo|baja)$"),
    escalon: str | None = Query(None, pattern="^(normal|aviso|restringido)$"),
    q: str | None = Query(None, max_length=100, description="alias, email o id"),
    orden: str = Query("alta", pattern="^(alta|karma|cargas)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: Usuario = Depends(exigir("usuario.ver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Pagina[UsuarioAdminOut]:
    c = Consulta()
    if tipo:
        c.condiciones.append("u.es_anonimo" if tipo == "anonimo" else "not u.es_anonimo")
    if rol:
        c.donde("u.rol = {}", rol)
    if estado:
        c.donde("u.estado = {}", estado)
    if escalon:
        # El escalón se deduce: se traduce a rangos de karma (un admin es siempre normal).
        aviso, restriccion = await moderacion.umbrales(pool)
        if escalon == "restringido":
            c.condiciones.append("u.rol = 'usuario'")
            c.donde("u.karma <= {}", restriccion)
        elif escalon == "aviso":
            c.condiciones.append("u.rol = 'usuario'")
            c.donde("u.karma <= {}", aviso)
            c.donde("u.karma > {}", restriccion)
        else:  # normal: un admin, o un usuario por encima de los dos umbrales
            c.condiciones.append(
                "(u.rol = 'admin' or u.karma > " + c.param(max(aviso, restriccion)) + ")"
            )
    if q and q.strip():
        p = c.param(f"%{escapar_like(q.strip().lower())}%")
        c.condiciones.append(
            f"(lower(u.alias) like {p} or lower(coalesce(u.email, '')) like {p}"
            f" or u.id::text like {p} or u.auth_id::text like {p})"
        )
    total = await pool.fetchval(f"select count(*) from usuarios u {c.where}", *c.args)
    lim, off = c.param(limit), c.param(offset)
    rows = await pool.fetch(
        f"{_SELECT} {c.where} order by {_ORDEN[orden]} limit {lim} offset {off}", *c.args
    )
    return Pagina(total=total, items=[await _salida(pool, r) for r in rows])


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioAdminOut)
async def editar_usuario(
    usuario_id: UUID,
    body: UsuarioPatch,
    admin: Usuario = Depends(exigir("usuario.editar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> UsuarioAdminOut:
    """Solo el alias. El rol y el karma NO se tocan desde acá (están protegidos en la base)."""
    if not body.alias.strip():
        raise HTTPException(422, "el alias no puede estar vacío")
    async with pool.acquire() as conn, conn.transaction():
        antes, alias = await servicio_alias.cambiar_por_admin(
            conn, pool, usuario_id, body.alias, admin.id
        )
        if antes != alias:
            await auditoria.registrar(
                conn,
                admin.id,
                "usuario.alias",
                "usuario",
                usuario_id,
                {"alias": antes},
                {"alias": alias},
            )
        row = await conn.fetchrow(f"{_SELECT} where u.id = $1", usuario_id)
    return await _salida(pool, row)


@router.get("/usuarios/{usuario_id}", response_model=UsuarioDetalle)
async def ficha_usuario(
    usuario_id: UUID,
    _: Usuario = Depends(exigir("usuario.ver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> UsuarioDetalle:
    row = await pool.fetchrow(f"{_SELECT} where u.id = $1", usuario_id)
    if row is None:
        raise HTTPException(404, "usuario no encontrado")
    cargas = await pool.fetch(
        """
        select p.id, p.precio, p.fecha, l.nombre as local_nombre, pc.ean,
               pc.nombre as producto_nombre
        from precios p join locales l on l.id = p.local_id
        left join productos_canonicos pc on pc.id = p.producto_canonico_id
        where p.user_id = $1 order by p.fecha desc limit 15
        """,
        usuario_id,
    )
    locales = await pool.fetch(
        "select id, nombre, verificado, fuente from locales where creado_por = $1 "
        "order by created_at desc limit 15",
        usuario_id,
    )
    return UsuarioDetalle(
        **(await _salida(pool, row)).model_dump(),
        cargas_recientes=[CargaOut(**dict(c)) for c in cargas],
        locales_creados_lista=[LocalCreadoOut(**dict(x)) for x in locales],
        historial=await historial(pool, "usuario", usuario_id),
        alias_historial=[
            AliasHistorialOut(**h) for h in await servicio_alias.historial(pool, usuario_id)
        ],
        mismo_dispositivo=[
            CuentaHermanaOut(**dict(c))
            for c in await dispositivos.cuentas_del_dispositivo(pool, usuario_id)
        ],
    )


@router.post("/usuarios/{usuario_id}/rol", response_model=UsuarioAdminOut)
async def cambiar_rol(
    usuario_id: UUID,
    body: RolIn,
    admin: Usuario = Depends(exigir("usuario.cambiar_rol")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> UsuarioAdminOut:
    """Cambia el rol. Reglas de negocio:
    - no podés cambiar el tuyo (nadie se escala ni se deja afuera por error);
    - un admin tiene que estar registrado (email): un anónimo no puede iniciar sesión en
      el panel y su sesión se pierde al reinstalar.
    El rol sigue protegido por trigger: se habilita solo dentro de esta transacción."""
    if usuario_id == admin.id:
        raise HTTPException(409, "no podés cambiar tu propio rol")
    async with pool.acquire() as conn, conn.transaction():
        u = await conn.fetchrow(
            "select rol, es_anonimo from usuarios where id = $1 for update", usuario_id
        )
        if u is None:
            raise HTTPException(404, "usuario no encontrado")
        if u["rol"] == body.rol:
            raise HTTPException(409, f"ya es {body.rol}")
        if body.rol == "admin" and u["es_anonimo"]:
            raise HTTPException(
                422, "un usuario anónimo no puede ser admin: tiene que ligar su cuenta a un email"
            )
        await conn.execute("select set_config('app.rol_write', 'on', true)")
        await conn.execute("update usuarios set rol = $2 where id = $1", usuario_id, body.rol)
        await auditoria.registrar(
            conn,
            admin.id,
            "usuario.rol",
            "usuario",
            usuario_id,
            {"rol": u["rol"]},
            {"rol": body.rol},
            nota=body.motivo,
        )
        row = await conn.fetchrow(f"{_SELECT} where u.id = $1", usuario_id)
    return await _salida(pool, row)


@router.post("/usuarios/{usuario_id}/karma", response_model=UsuarioAdminOut)
async def ajustar_karma(
    usuario_id: UUID,
    body: KarmaIn,
    admin: Usuario = Depends(exigir("usuario.ajustar_karma")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> UsuarioAdminOut:
    """Suma o resta karma a mano (premio o sanción). Exige un motivo; queda auditado."""
    if body.delta == 0:
        raise HTTPException(422, "el ajuste no puede ser cero")
    async with pool.acquire() as conn, conn.transaction():
        antes = await conn.fetchval(
            "select karma from usuarios where id = $1 for update", usuario_id
        )
        if antes is None:
            raise HTTPException(404, "usuario no encontrado")
        await conn.execute("select set_config('app.karma_write', 'on', true)")
        despues = await conn.fetchval(
            "update usuarios set karma = karma + $2 where id = $1 returning karma",
            usuario_id,
            body.delta,
        )
        await auditoria.registrar(
            conn,
            admin.id,
            "usuario.karma",
            "usuario",
            usuario_id,
            {"karma": antes},
            {"karma": despues},
            nota=body.motivo,
        )
        row = await conn.fetchrow(f"{_SELECT} where u.id = $1", usuario_id)
    return await _salida(pool, row)


async def _cambiar_estado(
    pool: asyncpg.Pool, admin: Usuario, usuario_id: UUID, nuevo: str, motivo: str
) -> UsuarioAdminOut:
    """Pone o saca la baja. El estado está protegido por trigger: se habilita solo dentro
    de esta transacción. El motivo y el antes/después quedan en la auditoría."""
    accion = "usuario.baja" if nuevo == "baja" else "usuario.reactivar"
    if usuario_id == admin.id:
        raise HTTPException(409, "no podés darte de baja (ni reactivarte) a vos mismo")
    async with pool.acquire() as conn, conn.transaction():
        u = await conn.fetchrow(
            "select estado, rol from usuarios where id = $1 for update", usuario_id
        )
        if u is None:
            raise HTTPException(404, "usuario no encontrado")
        if u["estado"] == nuevo:
            raise HTTPException(409, "ya está de baja" if nuevo == "baja" else "ya está activo")
        if nuevo == "baja" and u["rol"] == "admin":
            raise HTTPException(409, "es admin: primero sacale el rol y después dalo de baja")
        await conn.execute("select set_config('app.estado_write', 'on', true)")
        await conn.execute(
            "update usuarios set estado = $2, baja_at = case when $2 = 'baja' then now() end "
            "where id = $1",
            usuario_id,
            nuevo,
        )
        await auditoria.registrar(
            conn,
            admin.id,
            accion,
            "usuario",
            usuario_id,
            {"estado": u["estado"]},
            {"estado": nuevo},
            nota=motivo,
        )
        row = await conn.fetchrow(f"{_SELECT} where u.id = $1", usuario_id)
    return await _salida(pool, row)


@router.post("/usuarios/{usuario_id}/baja", response_model=UsuarioAdminOut)
async def dar_de_baja(
    usuario_id: UUID,
    body: BajaIn,
    admin: Usuario = Depends(exigir("usuario.dar_baja")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> UsuarioAdminOut:
    """Deja al usuario afuera: desde el próximo request no entra ni renueva sesión.
    Se puede revertir con `/reactivar`. Motivo obligatorio (queda en la auditoría)."""
    return await _cambiar_estado(pool, admin, usuario_id, "baja", body.motivo.strip())


@router.post("/usuarios/{usuario_id}/reactivar", response_model=UsuarioAdminOut)
async def reactivar(
    usuario_id: UUID,
    body: BajaIn,
    admin: Usuario = Depends(exigir("usuario.dar_baja")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> UsuarioAdminOut:
    return await _cambiar_estado(pool, admin, usuario_id, "activo", body.motivo.strip())


@router.post("/usuarios/{usuario_id}/reclamar", response_model=ReclamoOut)
async def reclamar_huerfana(
    usuario_id: UUID,
    body: ReclamoIn,
    admin: Usuario = Depends(exigir("usuario.reclamar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ReclamoOut:
    """Reclama una cuenta huérfana (anónima y activa) para esta cuenta ligada a Google: le
    pasa el karma y las cargas y la deja `fusionada`. Motivo obligatorio; queda auditado."""
    try:
        sin_pasar = await reclamos.reclamar(
            pool, admin.id, body.huerfana_id, usuario_id, body.motivo.strip()
        )
    except reclamos.ReclamoInvalido as e:
        raise HTTPException(e.http, e.mensaje) from e
    return ReclamoOut(filas_sin_pasar=sin_pasar)
