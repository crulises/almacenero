import os
import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.ratelimit import limitador
from tests.db import sql, valor_config

# El ciclo de programaciones se prueba llamando `vuelta` a mano; que no corra solo en los tests.
os.environ.setdefault("PROGRAMACIONES_ACTIVO", "false")


def make_token(sub: str | None = None) -> str:
    s = get_settings()
    now = int(time.time())
    return jwt.encode(
        {"sub": sub or str(uuid.uuid4()), "aud": s.jwt_audience, "iat": now, "exp": now + 3600},
        s.jwt_secret,
        algorithm="HS256",
    )


@pytest.fixture(scope="session")
def client():
    # Postgres real (el del Supabase CLI), con migraciones y seed aplicados.
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth():
    return {"Authorization": f"Bearer {make_token()}"}


@pytest.fixture(autouse=True)
def _limitador_limpio():
    """El rate limit vive en memoria: que un test no gaste el cupo de otro."""
    limitador.reiniciar()


@pytest.fixture
def config_temporal():
    """Cambia una clave de `config` durante el test y la restaura."""
    previos: dict[str, str | None] = {}

    def poner(clave: str, valor: str):
        previos.setdefault(clave, valor_config(clave))
        sql(
            """
            insert into config (clave, valor) values ($1, $2::jsonb)
            on conflict (clave, coalesce(rubro, '')) do update set valor = excluded.valor
            """,
            clave,
            valor,
        )

    yield poner
    for clave, previo in previos.items():
        if previo is None:
            sql("delete from config where clave = $1 and rubro is null", clave)
        else:
            sql(
                "update config set valor = $2::jsonb where clave = $1 and rubro is null",
                clave,
                previo,
            )
