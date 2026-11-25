"""Panel web de admin: `/v1/admin/...` (docs/04-plan-v0.0.2.md, §8).

Todo exige la capacidad `admin.acceder` y, además, la de cada acción (ver
`app/services/permisos.py`). Las correcciones dejan rastro en `auditoria_admin`.
"""

from datetime import datetime
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from app.api.v1.admin import (
    auditoria,
    catalogo,
    config,
    dashboard,
    etl,
    invitaciones,
    locales,
    precios,
    programaciones,
    reglas,
    sugerencias,
    usuarios,
)
from app.api.v1.auth import Sesion, _pedir_sesion, get_http
from app.auth import Usuario, current_user
from app.db import get_pool
from app.services.permisos import exigir, puede

router = APIRouter(prefix="/admin", tags=["admin"])


class LoginIn(BaseModel):
    email: str
    password: str


class AdminOut(BaseModel):
    id: UUID
    alias: str
    email: str | None
    rol: str
    karma: int
    created_at: datetime | None = None


class LoginOut(Sesion):
    usuario: AdminOut


async def _admin_out(pool: asyncpg.Pool, user: Usuario) -> AdminOut:
    row = await pool.fetchrow(
        "select id, alias, email, rol, karma, created_at from usuarios where id = $1", user.id
    )
    return AdminOut(**dict(row))


@router.post("/login", response_model=LoginOut)
async def login(
    body: LoginIn,
    http: httpx.AsyncClient = Depends(get_http),
    pool: asyncpg.Pool = Depends(get_pool),
) -> LoginOut:
    """Email y contraseña (GoTrue), vía el backend. Solo entra quien tiene rol admin:
    a cualquier otra cuenta se le devuelve 403 y no se le entrega la sesión."""
    sesion = await _pedir_sesion(
        http, "/token?grant_type=password", {"email": body.email.strip(), "password": body.password}
    )
    user = await current_user(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=sesion.access_token), pool
    )
    if not puede(user, "admin.acceder"):
        raise HTTPException(403, "esta cuenta no es de admin")
    return LoginOut(**sesion.model_dump(), usuario=await _admin_out(pool, user))


@router.get("/me", response_model=AdminOut)
async def admin_me(
    user: Usuario = Depends(exigir("admin.acceder")), pool: asyncpg.Pool = Depends(get_pool)
) -> AdminOut:
    return await _admin_out(pool, user)


_acceso = [Depends(exigir("admin.acceder"))]
router.include_router(usuarios.router, dependencies=_acceso)
router.include_router(locales.router, dependencies=_acceso)
router.include_router(precios.router, dependencies=_acceso)
router.include_router(config.router, dependencies=_acceso)
router.include_router(reglas.router, dependencies=_acceso)
router.include_router(catalogo.router, dependencies=_acceso)
router.include_router(sugerencias.router, dependencies=_acceso)
router.include_router(invitaciones.router, dependencies=_acceso)
router.include_router(dashboard.router, dependencies=_acceso)
router.include_router(etl.router, dependencies=_acceso)
router.include_router(programaciones.router, dependencies=_acceso)
router.include_router(auditoria.router, dependencies=_acceso)
