"""Crea (o promueve) un admin con email y contraseña, para entrar al panel web.

    python -m app.admin_cli EMAIL [PASSWORD]      (o: make admin-crear EMAIL=...)

Registra la cuenta en el proveedor de auth (GoTrue) si no existe —o verifica la
contraseña si ya existe— y le pone `rol = 'admin'` en `usuarios`. El rol está protegido
por un trigger: se habilita solo dentro de esta transacción, igual que `make admin`.
"""

import argparse
import asyncio
import getpass
import sys

import asyncpg
import httpx

from app.config import get_settings


def _pedir_id_de_auth(email: str, password: str) -> str:
    s = get_settings()
    if not s.auth_url or not s.auth_api_key:
        sys.exit("Falta AUTH_URL / AUTH_API_KEY (¿corriste `make up`?)")
    cab = {"apikey": s.auth_api_key}
    r = httpx.post(f"{s.auth_url}/signup", json={"email": email, "password": password}, headers=cab)
    if r.status_code < 300:
        d = r.json()
        user = d.get("user") or d
        if user.get("id") and (d.get("access_token") or user.get("email")):
            return user["id"]
    # Ya existía (o no devolvió sesión): verificar la contraseña iniciando sesión.
    r = httpx.post(
        f"{s.auth_url}/token?grant_type=password",
        json={"email": email, "password": password},
        headers=cab,
    )
    if r.status_code >= 300:
        sys.exit(f"No pude crear ni iniciar sesión con ese email ({r.status_code}): {r.text}")
    return r.json()["user"]["id"]


async def _promover(auth_id: str, email: str) -> str:
    conn = await asyncpg.connect(get_settings().database_url)
    try:
        async with conn.transaction():
            await conn.execute("select set_config('app.rol_write', 'on', true)")
            return await conn.fetchval(
                """
                insert into usuarios (auth_id, alias, email, es_anonimo, rol)
                values ($1::uuid, $2, $3, false, 'admin')
                on conflict (auth_id) do update
                    set rol = 'admin', email = excluded.email, es_anonimo = false
                returning alias
                """,
                auth_id,
                f"admin-{auth_id[:6]}",
                email,
            )
    finally:
        await conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("email")
    ap.add_argument("password", nargs="?", help="si falta, se pide por teclado")
    args = ap.parse_args()
    email = args.email.strip().lower()
    password = args.password or getpass.getpass("Contraseña (mín. 6 caracteres): ")
    auth_id = _pedir_id_de_auth(email, password)
    alias = asyncio.run(_promover(auth_id, email))
    print(f"Listo: {email} es admin (alias {alias}). Entrá al panel con ese email.")


if __name__ == "__main__":
    main()
