import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


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
