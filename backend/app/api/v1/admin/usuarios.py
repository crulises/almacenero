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
from app.services import auditoria
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
    cargas: int
    locales_creados: int
    created_at: datetime


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


class UsuarioDetalle(UsuarioAdminOut):
    """La ficha del usuario: identidad, actividad y cambios anteriores."""

    cargas_recientes: list[CargaOut]
    locales_creados_lista: list[LocalCreadoOut]
    historial: list[AuditoriaOut]


class RolIn(BaseModel):
    rol: str = Field(pattern="^(usuario|admin)$")
    motivo: str | None = Field(default=None, max_length=300)


class KarmaIn(BaseModel):
    delta: int = Field(ge=-1000, le=1000)
    motivo: str = Field(min_length=3, max_length=300)


class UsuarioPatch(BaseModel):
    alias: str = Field(min_length=1, max_length=50)


_SELECT = """
    select u.id, u.auth_id, u.alias, u.email, u.es_anonimo, u.anonimo_auth_id, u.rol,
           u.karma, u.created_at,
           (select count(*) from precios p where p.user_id = u.id) as cargas,
           (select count(*) from locales l where l.creado_por = u.id) as locales_creados
    from usuarios u
"""


@router.get("/usuarios", response_model=Pagina[UsuarioAdminOut])
async def listar_usuarios(
    tipo: str | None = Query(None, pattern="^(anonimo|registrado)$"),
    rol: str | None = Query(None, pattern="^(usuario|admin)$"),
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
    return Pagina(total=total, items=[UsuarioAdminOut(**dict(r)) for r in rows])


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioAdminOut)
async def editar_usuario(
    usuario_id: UUID,
    body: UsuarioPatch,
    admin: Usuario = Depends(exigir("usuario.editar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> UsuarioAdminOut:
    """Solo el alias. El rol y el karma NO se tocan desde acá (están protegidos en la base)."""
    alias = body.alias.strip()
    if not alias:
        raise HTTPException(422, "el alias no puede estar vacío")
    async with pool.acquire() as conn, conn.transaction():
        antes = await conn.fetchval(
            "select alias from usuarios where id = $1 for update", usuario_id
        )
        if antes is None:
            raise HTTPException(404, "usuario no encontrado")
        await conn.execute("update usuarios set alias = $2 where id = $1", usuario_id, alias)
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
    return UsuarioAdminOut(**dict(row))


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
        **dict(row),
        cargas_recientes=[CargaOut(**dict(c)) for c in cargas],
        locales_creados_lista=[LocalCreadoOut(**dict(x)) for x in locales],
        historial=await historial(pool, "usuario", usuario_id),
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
    return UsuarioAdminOut(**dict(row))


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
    return UsuarioAdminOut(**dict(row))
