"""Validación del JWT del proveedor de auth y alta perezosa del usuario."""

from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import asyncpg
import jwt
from fastapi import Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.db import get_pool
from app.services import moderacion

bearer = HTTPBearer(auto_error=False)

CUENTA_BAJA = {
    "codigo": "cuenta_baja",
    "mensaje": "tu cuenta fue dada de baja: ya no podés usar Almacenero",
}


@dataclass
class Usuario:
    id: UUID
    auth_id: UUID
    alias: str
    karma: int
    rol: str = "usuario"
    estado: str = "activo"
    # Escalón por karma (docs/04 §9): normal | aviso | restringido. Deducido, no guardado.
    escalon: str = "normal"
    umbral_restriccion: int = -15


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    # Cachea las claves públicas; se refresca solo si aparece un `kid` desconocido.
    return jwt.PyJWKClient(url)


def decode_token(token: str) -> dict:
    """Valida el JWT. Asimétrico (ES256/RS256) contra el JWKS del proveedor de auth;
    HS256 con secreto compartido como alternativa."""
    s = get_settings()
    try:
        alg = jwt.get_unverified_header(token).get("alg")
        if alg == "HS256":
            key, algs = s.jwt_secret, ["HS256"]
        elif alg in ("ES256", "RS256") and s.jwks_url:
            key = _jwks_client(s.jwks_url).get_signing_key_from_jwt(token).key
            algs = [alg]
        else:
            raise HTTPException(status_code=401, detail="algoritmo de token no soportado")
        return jwt.decode(token, key, algorithms=algs, audience=s.jwt_audience)
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail="token inválido") from e


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Usuario:
    if creds is None:
        raise HTTPException(status_code=401, detail="falta token")
    # sync (la primera vez baja el JWKS por red): fuera del event loop.
    claims = await run_in_threadpool(decode_token, creds.credentials)
    try:
        auth_id = UUID(claims["sub"])
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=401, detail="token sin sub válido") from e

    # `is_anonymous` y `email` vienen del proveedor (GoTrue). Sin el claim, se es anónimo
    # salvo que haya email.
    email = claims.get("email") or None
    es_anonimo = bool(claims.get("is_anonymous", email is None))
    row = await pool.fetchrow(
        """
        insert into usuarios (auth_id, alias, email, es_anonimo, anonimo_auth_id)
        values ($1, $2, $3, $4, case when $4::boolean then $1::uuid end)
        on conflict (auth_id) do update
            set email = coalesce(excluded.email, usuarios.email),
                es_anonimo = excluded.es_anonimo
        returning id, auth_id, alias, karma, rol, estado
        """,
        auth_id,
        f"anon-{str(auth_id)[:6]}",
        email,
        es_anonimo,
    )
    datos = dict(row)
    if datos["estado"] == "baja":
        # Vale en el siguiente request, aunque el token siga vigente. 403 y no 401: un 401
        # haría que la app «empiece de nuevo» con otra cuenta anónima.
        raise HTTPException(status_code=403, detail=CUENTA_BAJA)
    aviso, restriccion = await moderacion.umbrales(pool)
    return Usuario(
        **datos,
        escalon=moderacion.NORMAL
        if datos["rol"] == "admin"
        else moderacion.escalon(datos["karma"], aviso, restriccion),
        umbral_restriccion=restriccion,
    )
