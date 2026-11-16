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

bearer = HTTPBearer(auto_error=False)


@dataclass
class Usuario:
    id: UUID
    auth_id: UUID
    alias: str
    karma: int
    rol: str = "usuario"


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

    row = await pool.fetchrow(
        """
        insert into usuarios (auth_id, alias) values ($1, $2)
        on conflict (auth_id) do update set auth_id = excluded.auth_id
        returning id, auth_id, alias, karma, rol
        """,
        auth_id,
        f"anon-{str(auth_id)[:6]}",
    )
    return Usuario(**dict(row))
