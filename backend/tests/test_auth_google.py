"""/v1/auth/google/*: ligar la cuenta anónima a Google y entrar con una cuenta ya ligada
(docs/superpowers/specs/2026-11-26-cuentas-ligables-design.md). GoTrue se simula con
MockTransport (servicio externo); Postgres es real."""

import json
import time
import uuid

import httpx
import jwt
import pytest

from app.config import get_settings
from app.main import app
from tests.conftest import make_token
from tests.db import fila


def sesion_de(sub: str, email: str | None = "") -> dict:
    """Respuesta de GoTrue con un access token que dice quién es (sin firma verificable).
    `email` vacío = uno propio de esa cuenta (el email es único en `usuarios`); None = sin email."""
    if email == "":
        email = f"{sub}@example.com"
    claims = {"sub": sub, "iat": int(time.time()), "is_anonymous": False}
    if email:
        claims["email"] = email
    tok = jwt.encode(claims, "x", algorithm="HS256")
    return {"access_token": tok, "refresh_token": "ref", "expires_in": 3600}


@pytest.fixture
def google(client, monkeypatch, config_temporal):
    """GoTrue simulado: `e` fija la respuesta (status, json) y junta lo recibido (visto)."""
    config_temporal("modo_acceso", '"abierto"')
    s = get_settings()
    monkeypatch.setattr(s, "auth_url", "http://auth.test/auth/v1")
    monkeypatch.setattr(s, "auth_api_key", "clave-publica")
    e = {"status": 200, "json": None, "visto": []}

    def handler(req: httpx.Request) -> httpx.Response:
        e["visto"].append(req)
        return httpx.Response(e["status"], json=e["json"])

    original = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    yield e
    app.state.http = original


def nueva_cuenta(client) -> tuple[dict, str, str]:
    """Cuenta anónima recién creada: (headers, usuarios.id, auth_id)."""
    auth_id = str(uuid.uuid4())
    h = {"Authorization": f"Bearer {make_token(auth_id)}"}
    return h, client.get("/v1/me", headers=h).json()["id"], auth_id


def test_ligar_ok_conserva_el_mismo_usuario(client, google):
    h, uid, auth_id = nueva_cuenta(client)
    alias = fila("select alias from usuarios where id = $1::uuid", uid)["alias"]
    google["json"] = sesion_de(auth_id)

    r = client.post("/v1/auth/google/ligar", headers=h, json={"id_token": "tok-google"})

    assert r.status_code == 200
    assert r.json()["refresh_token"] == "ref"
    pedido = google["visto"][0]
    assert pedido.url.path == "/auth/v1/token" and pedido.url.query == b"grant_type=id_token"
    cuerpo = json.loads(pedido.content)
    assert cuerpo == {
        "provider": "google",
        "id_token": "tok-google",
        "link_identity": True,
    }
    assert pedido.headers["authorization"] == h["Authorization"]
    u = fila("select id, alias, email, es_anonimo from usuarios where auth_id = $1::uuid", auth_id)
    assert str(u["id"]) == uid and u["alias"] == alias
    assert u["email"] == f"{auth_id}@example.com" and u["es_anonimo"] is False


def test_ligar_manda_el_nonce_si_hay(client, google):
    h, _, auth_id = nueva_cuenta(client)
    google["json"] = sesion_de(auth_id)
    client.post("/v1/auth/google/ligar", headers=h, json={"id_token": "t", "nonce": "n-1"})
    assert json.loads(google["visto"][0].content)["nonce"] == "n-1"


def test_ligar_google_ya_ligado_409(client, google):
    h, uid, auth_id = nueva_cuenta(client)
    google["status"] = 422
    google["json"] = {"code": 422, "error_code": "identity_already_exists", "msg": "ya existe"}

    r = client.post("/v1/auth/google/ligar", headers=h, json={"id_token": "t"})

    assert r.status_code == 409
    assert r.json()["detail"]["codigo"] == "google_ya_ligado"
    u = fila("select email, es_anonimo from usuarios where id = $1::uuid", uid)
    assert u["email"] is None and u["es_anonimo"] is True


def test_ligar_id_token_vencido_o_invalido_es_401(client, google):
    h, _, _ = nueva_cuenta(client)
    google["status"] = 400
    google["json"] = {"error_code": "validation_failed", "msg": "Bad ID token"}
    r = client.post("/v1/auth/google/ligar", headers=h, json={"id_token": "vencido"})
    assert r.status_code == 401


def test_ligar_una_cuenta_ya_ligada_409_sin_llamar_al_proveedor(client, google):
    h, _, auth_id = nueva_cuenta(client)
    google["json"] = sesion_de(auth_id)
    primero = client.post("/v1/auth/google/ligar", headers=h, json={"id_token": "t"})
    assert primero.status_code == 200
    google["visto"].clear()

    r = client.post("/v1/auth/google/ligar", headers=h, json={"id_token": "t"})

    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "ya_ligada"
    assert google["visto"] == []


def test_ligar_sin_sesion_401(client, google):
    assert client.post("/v1/auth/google/ligar", json={"id_token": "t"}).status_code == 401


def test_una_cuenta_ligada_no_vuelve_a_anonima_con_un_token_viejo(client, google):
    """El token anterior al ligado todavía dice `is_anonymous`; no debe revertir la cuenta."""
    h, uid, auth_id = nueva_cuenta(client)
    google["json"] = sesion_de(auth_id)
    client.post("/v1/auth/google/ligar", headers=h, json={"id_token": "t"})

    client.get("/v1/me", headers=h)  # token viejo, sin claims de email

    assert fila("select es_anonimo from usuarios where id = $1::uuid", uid)["es_anonimo"] is False
