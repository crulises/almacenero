from datetime import datetime
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

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
