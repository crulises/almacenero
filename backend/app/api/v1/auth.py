"""Proxy de auth: el cliente habla solo con el backend, nunca con el proveedor de auth.

El backend pide la sesión al proveedor (GoTrue) y la devuelve tal cual. La validación de
los tokens en cada request sigue en `app/auth.py`.
"""

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db import get_pool
from app.services import config, invitaciones
from app.services.ratelimit import ip_cliente, limitar

router = APIRouter(prefix="/auth", tags=["auth"])


class Sesion(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class AnonimaIn(BaseModel):
    # Solo hace falta con `modo_acceso = solo_invitacion`.
    codigo_invitacion: str | None = Field(default=None, max_length=64)


class RefreshIn(BaseModel):
    refresh_token: str


async def get_http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


async def _pedir_sesion(http: httpx.AsyncClient, path: str, body: dict) -> Sesion:
    s = get_settings()
    if not s.auth_url or not s.auth_api_key:
        raise HTTPException(503, "auth no configurada (AUTH_URL / AUTH_API_KEY)")
    try:
        r = await http.post(
            f"{s.auth_url}{path}",
            json=body,
            headers={"apikey": s.auth_api_key},
            timeout=10,
        )
    except httpx.HTTPError as e:
        raise HTTPException(502, "proveedor de auth no disponible") from e
    if r.status_code in (400, 401, 403, 422):
        raise HTTPException(401, "sesión inválida")
    if r.status_code >= 400:
        raise HTTPException(502, "error del proveedor de auth")
    d = r.json()
    return Sesion(
        access_token=d["access_token"],
        refresh_token=d["refresh_token"],
        expires_in=d["expires_in"],
    )


@router.post("/anonymous", response_model=Sesion)
async def sesion_anonima(
    request: Request,
    body: AnonimaIn | None = None,
    http: httpx.AsyncClient = Depends(get_http),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Sesion:
    """Crea un usuario anónimo y devuelve su sesión (la app lo llama en el primer
    arranque). Defensas, en orden (docs/04 §6): rate limit por IP, `modo_acceso` y
    código de invitación. Se cuentan todos los intentos, también los de código malo:
    frena el adivinar códigos."""
    limite = int(await config.leer(pool, "auth_altas_por_hora_ip"))
    limitar(
        f"anonymous:{ip_cliente(request)}",
        limite,
        3600,
        "demasiados intentos desde esta conexión: probá más tarde",
    )

    modo = await config.leer(pool, "modo_acceso")
    if modo == "abierto":
        return await _pedir_sesion(http, "/signup", {})
    if modo != "solo_invitacion":  # alta_manual, o un valor que no entendemos
        raise HTTPException(
            403,
            detail={
                "codigo": "alta_cerrada",
                "mensaje": "las altas están cerradas: pedile al admin que te cree el usuario",
            },
        )

    codigo = body.codigo_invitacion if body else None
    if not codigo or not codigo.strip():
        raise HTTPException(
            403,
            detail={"codigo": "invitacion_requerida", "mensaje": "falta el código de invitación"},
        )
    invitacion_id = await invitaciones.consumir(pool, codigo)
    if invitacion_id is None:
        raise HTTPException(
            403,
            detail={"codigo": "invitacion_invalida", "mensaje": "código de invitación inválido"},
        )
    try:
        return await _pedir_sesion(http, "/signup", {})
    except HTTPException:
        await invitaciones.devolver(pool, invitacion_id)  # no se gastó una invitación en vano
        raise


@router.post("/refresh", response_model=Sesion)
async def renovar_sesion(
    request: Request,
    body: RefreshIn,
    http: httpx.AsyncClient = Depends(get_http),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Sesion:
    limite = int(await config.leer(pool, "auth_refresh_por_hora_ip"))
    limitar(
        f"refresh:{ip_cliente(request)}",
        limite,
        3600,
        "demasiados intentos desde esta conexión: probá más tarde",
    )
    return await _pedir_sesion(
        http, "/token?grant_type=refresh_token", {"refresh_token": body.refresh_token}
    )
