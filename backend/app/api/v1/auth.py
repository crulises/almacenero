"""Proxy de auth: el cliente habla solo con el backend, nunca con el proveedor de auth.

El backend pide la sesión al proveedor (GoTrue) y la devuelve tal cual. La validación de
los tokens en cada request sigue en `app/auth.py`.
"""

from uuid import UUID

import asyncpg
import httpx
import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.auth import (
    CUENTA_BAJA,
    CUENTA_FUSIONADA,
    Usuario,
    asegurar_usuario,
    bearer,
    current_user,
)
from app.config import get_settings
from app.db import get_pool
from app.services import config, dispositivos, invitaciones
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


class GoogleIn(BaseModel):
    """`id_token` que da Google Sign-In en el celular (cliente Web como `serverClientId`)."""

    id_token: str = Field(max_length=4096)
    nonce: str | None = Field(default=None, max_length=256)
    # Solo para `/google/entrar` con una cuenta nueva y `modo_acceso = solo_invitacion`.
    codigo_invitacion: str | None = Field(default=None, max_length=64)


GOOGLE_YA_LIGADO = {
    "codigo": "google_ya_ligado",
    "mensaje": "ese Google ya tiene una cuenta: entrá con ella",
}
EMAIL_EN_USO = {
    "codigo": "email_en_uso",
    "mensaje": "ese email ya lo usa otra cuenta: pedile al admin que las una",
}
YA_LIGADA = {"codigo": "ya_ligada", "mensaje": "tu cuenta ya está ligada a Google"}


async def get_http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


async def _pedir_sesion(
    http: httpx.AsyncClient, path: str, body: dict, bearer: str | None = None
) -> Sesion:
    s = get_settings()
    if not s.auth_url or not s.auth_api_key:
        raise HTTPException(503, "auth no configurada (AUTH_URL / AUTH_API_KEY)")
    headers = {"apikey": s.auth_api_key}
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        r = await http.post(f"{s.auth_url}{path}", json=body, headers=headers, timeout=10)
    except httpx.HTTPError as e:
        raise HTTPException(502, "proveedor de auth no disponible") from e
    if r.status_code == 422 and _error_code(r) == "identity_already_exists":
        raise HTTPException(409, detail=GOOGLE_YA_LIGADO)
    if r.status_code == 422 and _error_code(r) == "email_exists":
        raise HTTPException(409, detail=EMAIL_EN_USO)
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


def _error_code(r: httpx.Response) -> str | None:
    try:
        return r.json().get("error_code")
    except (ValueError, AttributeError):
        return None


def _claims_de(access_token: str) -> dict:
    """Claims del token que nos acaba de dar el proveedor. Sin verificar la firma a
    propósito: no es una credencial que recibimos, es la respuesta directa de nuestro
    proveedor y solo se usa para anotar datos (quién es, su email)."""
    try:
        return jwt.decode(access_token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return {}


def _auth_id_de(access_token: str) -> UUID | None:
    try:
        return UUID(_claims_de(access_token)["sub"])
    except (KeyError, ValueError):
        return None


async def _pedir_sesion_google(
    http: httpx.AsyncClient, body: GoogleIn, bearer: str | None
) -> Sesion:
    """`POST /token?grant_type=id_token` de GoTrue. Con `bearer` liga la identidad de Google a
    ESA cuenta (`link_identity`, conserva el `auth_id`); sin él, inicia sesión (y GoTrue crea
    la cuenta si ese Google no se conocía)."""
    pedido: dict = {"provider": "google", "id_token": body.id_token}
    if body.nonce is not None:
        pedido["nonce"] = body.nonce
    if bearer is not None:
        pedido["link_identity"] = True
    return await _pedir_sesion(http, "/token?grant_type=id_token", pedido, bearer)


async def _anotar_dispositivo(
    pool: asyncpg.Pool, sesion: Sesion, dispositivo: str | None
) -> Sesion:
    """Asocia el dispositivo a la cuenta de la sesión (si hay ID y se pudo leer el token)."""
    auth_id = _auth_id_de(sesion.access_token)
    if dispositivo is not None and auth_id is not None:
        await dispositivos.registrar(pool, dispositivo, auth_id)
    return sesion


async def _admitir_alta(pool: asyncpg.Pool, codigo: str | None) -> invitaciones.Uso | None:
    """Defensas de un alta nueva (anónima o por Google): `modo_acceso` y código de invitación.
    Devuelve el uso de invitación gastado (None si el modo es abierto); 403 si no se admite."""
    modo = await config.leer(pool, "modo_acceso")
    if modo == "abierto":
        return None
    if modo != "solo_invitacion":  # alta_manual, o un valor que no entendemos
        raise HTTPException(
            403,
            detail={
                "codigo": "alta_cerrada",
                "mensaje": "las altas están cerradas: pedile al admin que te cree el usuario",
            },
        )
    if not codigo or not codigo.strip():
        raise HTTPException(
            403,
            detail={"codigo": "invitacion_requerida", "mensaje": "falta el código de invitación"},
        )
    uso = await invitaciones.consumir(pool, codigo)
    if uso is None:
        raise HTTPException(
            403,
            detail={"codigo": "invitacion_invalida", "mensaje": "código de invitación inválido"},
        )
    return uso


@router.post("/anonymous", response_model=Sesion)
async def sesion_anonima(
    request: Request,
    body: AnonimaIn | None = None,
    x_device_id: str | None = Header(default=None),
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

    # Un dispositivo que ya tuvo una cuenta de baja no crea otra (docs/04 §9). Va antes
    # que el PIN: no se gasta una invitación en vano.
    dispositivo = dispositivos.hashear(x_device_id)
    if dispositivo is not None and await dispositivos.tiene_baja(pool, dispositivo):
        raise HTTPException(403, detail=CUENTA_BAJA)

    uso = await _admitir_alta(pool, body.codigo_invitacion if body else None)
    try:
        sesion = await _pedir_sesion(http, "/signup", {})
    except HTTPException:
        if uso is not None:
            await invitaciones.devolver(pool, uso)  # no se gastó una invitación en vano
        raise
    auth_id = _auth_id_de(sesion.access_token)
    if uso is not None and auth_id is not None:  # para que el panel muestre quién usó el código
        await invitaciones.anotar_usuario(pool, uso, auth_id)
    return await _anotar_dispositivo(pool, sesion, dispositivo)


@router.post("/refresh", response_model=Sesion)
async def renovar_sesion(
    request: Request,
    body: RefreshIn,
    x_device_id: str | None = Header(default=None),
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
    sesion = await _pedir_sesion(
        http, "/token?grant_type=refresh_token", {"refresh_token": body.refresh_token}
    )
    # Cuenta dada de baja (docs/04 §9): el proveedor renovó, pero acá no se entrega la
    # sesión. 403 y no 401: un 401 haría que la app se cree otra cuenta anónima.
    auth_id = _auth_id_de(sesion.access_token)
    estado = (
        await pool.fetchval("select estado from usuarios where auth_id = $1", auth_id)
        if auth_id is not None
        else None
    )
    if estado == "baja":
        raise HTTPException(403, detail=CUENTA_BAJA)
    if estado == "fusionada":
        raise HTTPException(403, detail=CUENTA_FUSIONADA)
    # Cuentas que ya existían: el refresh las asocia a su dispositivo.
    return await _anotar_dispositivo(pool, sesion, dispositivos.hashear(x_device_id))


@router.post("/google/ligar", response_model=Sesion)
async def ligar_google(
    body: GoogleIn,
    user: Usuario = Depends(current_user),
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    x_device_id: str | None = Header(default=None),
    http: httpx.AsyncClient = Depends(get_http),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Sesion:
    """Liga la cuenta anónima a Google. Es la MISMA cuenta (mismo `usuarios.id`, karma y alias):
    GoTrue conserva el `auth_id`. Devuelve la sesión nueva, que ya no dice `is_anonymous`: la
    app tiene que guardarla. Si ese Google ya es de otra cuenta, 409 `google_ya_ligado`."""
    if not user.es_anonimo:
        raise HTTPException(409, detail=YA_LIGADA)
    sesion = await _pedir_sesion_google(http, body, creds.credentials if creds else None)
    email = _claims_de(sesion.access_token).get("email") or None
    await pool.execute(
        # El email solo se anota si ninguna otra fila lo tiene (es único): si no, igual se liga.
        "update usuarios set es_anonimo = false, email = coalesce("
        "(select $2::text where not exists "
        "(select 1 from usuarios o where o.email = $2::text and o.id <> $1)), email) "
        "where id = $1",
        user.id,
        email,
    )
    return await _anotar_dispositivo(pool, sesion, dispositivos.hashear(x_device_id))


@router.post("/google/entrar", response_model=Sesion)
async def entrar_google(
    request: Request,
    body: GoogleIn,
    x_device_id: str | None = Header(default=None),
    http: httpx.AsyncClient = Depends(get_http),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Sesion:
    """Abre sesión con una cuenta ya ligada a Google (reinstalación u otro celular), sin PIN.

    Si ese Google no se conocía, GoTrue crea una cuenta nueva: esa pasa por las mismas defensas
    que el alta anónima (rate limit de altas, dispositivo con baja, `modo_acceso` y PIN). Una
    cuenta rechazada nunca recibe sesión nuestra: el cliente solo obtiene tokens por acá."""
    ip = ip_cliente(request)
    limitar(
        f"google_entrar:{ip}",
        int(await config.leer(pool, "auth_refresh_por_hora_ip")),
        3600,
        "demasiados intentos desde esta conexión: probá más tarde",
    )
    sesion = await _pedir_sesion_google(http, body, None)
    auth_id = _auth_id_de(sesion.access_token)
    if auth_id is None:
        raise HTTPException(502, "error del proveedor de auth")
    dispositivo = dispositivos.hashear(x_device_id)

    estado = await pool.fetchval("select estado from usuarios where auth_id = $1", auth_id)
    if estado == "baja":
        raise HTTPException(403, detail=CUENTA_BAJA)
    if estado == "fusionada":
        raise HTTPException(403, detail=CUENTA_FUSIONADA)
    if estado is None:  # cuenta nueva: es un alta más
        limitar(
            f"anonymous:{ip}",
            int(await config.leer(pool, "auth_altas_por_hora_ip")),
            3600,
            "demasiados intentos desde esta conexión: probá más tarde",
        )
        if dispositivo is not None and await dispositivos.tiene_baja(pool, dispositivo):
            raise HTTPException(403, detail=CUENTA_BAJA)
        uso = await _admitir_alta(pool, body.codigo_invitacion)
        email = _claims_de(sesion.access_token).get("email") or None
        try:
            await asegurar_usuario(pool, auth_id, email, es_anonimo=False)
        except Exception:
            if uso is not None:
                await invitaciones.devolver(pool, uso)
            raise
        if uso is not None:
            await invitaciones.anotar_usuario(pool, uso, auth_id)
    return await _anotar_dispositivo(pool, sesion, dispositivo)
