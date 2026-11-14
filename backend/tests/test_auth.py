import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from app import auth
from app.config import get_settings


def _es256_token(private_key, aud="authenticated"):
    now = int(time.time())
    return jwt.encode(
        {"sub": str(uuid.uuid4()), "aud": aud, "iat": now, "exp": now + 60},
        private_key,
        algorithm="ES256",
        headers={"kid": "test"},
    )


class _FakeJWKS:
    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key_from_jwt(self, _token):
        return type("K", (), {"key": self.public_key})()


def test_token_es256_valido(monkeypatch):
    priv = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(auth, "_jwks_client", lambda _url: _FakeJWKS(priv.public_key()))
    claims = auth.decode_token(_es256_token(priv))
    assert claims["aud"] == get_settings().jwt_audience


def test_token_es256_firma_ajena_rechazado(monkeypatch):
    priv, otra = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(auth, "_jwks_client", lambda _url: _FakeJWKS(otra.public_key()))
    with pytest.raises(HTTPException) as e:
        auth.decode_token(_es256_token(priv))
    assert e.value.status_code == 401
