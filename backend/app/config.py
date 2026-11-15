from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración por variables de entorno. Nada acoplado a Supabase por nombre."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Cualquier Postgres con PostGIS. Por defecto, el del Supabase CLI local.
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"

    # Secreto con el que el proveedor de auth firma los JWT (HS256).
    # JWKS / otros proveedores: extender en app/auth.py.
    # API del proveedor de auth (GoTrue), usada por /v1/auth/*. La api key es la
    # "anon"/"publishable" del proveedor (`supabase status`); no es un secreto fuerte.
    auth_url: str | None = "http://127.0.0.1:54321/auth/v1"
    auth_api_key: str | None = None

    # JWKS del proveedor de auth (tokens ES256/RS256, el default del Supabase CLI nuevo).
    jwks_url: str | None = "http://127.0.0.1:54321/auth/v1/.well-known/jwks.json"
    jwt_secret: str = "super-secret-jwt-token-with-at-least-32-characters-long"
    jwt_audience: str = "authenticated"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
