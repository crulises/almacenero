"""/v1/auth/*: proxy del proveedor de auth. El proveedor se simula con MockTransport
(es un servicio externo; Postgres sigue siendo real en el resto de los tests)."""

import httpx
import pytest

from app.config import get_settings
from app.main import app

SESION = {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600}


@pytest.fixture
def proveedor(client, monkeypatch):
    """Reemplaza el cliente HTTP del backend por uno simulado; devuelve los requests vistos."""
    s = get_settings()
    monkeypatch.setattr(s, "auth_url", "http://auth.test/auth/v1")
    monkeypatch.setattr(s, "auth_api_key", "clave-publica")
    vistos: list[httpx.Request] = []
    respuesta = {"status": 200, "json": SESION}

    def handler(req: httpx.Request) -> httpx.Response:
        vistos.append(req)
        return httpx.Response(respuesta["status"], json=respuesta["json"])

    original = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    yield vistos, respuesta
    app.state.http = original


def test_sesion_anonima(client, proveedor):
    vistos, _ = proveedor
    r = client.post("/v1/auth/anonymous")
    assert r.status_code == 200
    assert r.json() == SESION
    assert vistos[0].url.path == "/auth/v1/signup"
    assert vistos[0].headers["apikey"] == "clave-publica"


def test_refresh(client, proveedor):
    vistos, _ = proveedor
    r = client.post("/v1/auth/refresh", json={"refresh_token": "ref"})
    assert r.status_code == 200
    assert vistos[0].url.query == b"grant_type=refresh_token"


def test_refresh_invalido_401(client, proveedor):
    _, respuesta = proveedor
    respuesta.update(status=400, json={"error": "invalid_grant"})
    assert client.post("/v1/auth/refresh", json={"refresh_token": "x"}).status_code == 401


def test_proveedor_caido_502(client, proveedor):
    _, respuesta = proveedor
    respuesta.update(status=500, json={})
    assert client.post("/v1/auth/anonymous").status_code == 502


def test_sin_api_key_503(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_api_key", None)
    assert client.post("/v1/auth/anonymous").status_code == 503
