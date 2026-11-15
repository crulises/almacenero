"""Proxy de auth: el cliente habla solo con el backend, nunca con el proveedor de auth.

El backend pide la sesión al proveedor (GoTrue) y la devuelve tal cual. La validación de
los tokens en cada request sigue en `app/auth.py`.
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class Sesion(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


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
async def sesion_anonima(http: httpx.AsyncClient = Depends(get_http)) -> Sesion:
    """Crea un usuario anónimo y devuelve su sesión. Sin fricción: la app lo llama
    en el primer arranque. (Rate limiting: pendiente, ver anti-spam en el Doc 1.)"""
    return await _pedir_sesion(http, "/signup", {})


@router.post("/refresh", response_model=Sesion)
async def renovar_sesion(body: RefreshIn, http: httpx.AsyncClient = Depends(get_http)) -> Sesion:
    return await _pedir_sesion(
        http, "/token?grant_type=refresh_token", {"refresh_token": body.refresh_token}
    )
