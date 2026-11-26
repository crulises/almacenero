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
from app.services import dispositivos
from tests.conftest import make_token
from tests.db import fila, poner_estado, sql


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


# ------------------------------------------------------------------ /auth/google/entrar


def entrar(client, **extra):
    cuerpo = {"id_token": "tok-google"} | {k: v for k, v in extra.items() if k != "device"}
    h = {"X-Device-Id": extra["device"]} if "device" in extra else {}
    return client.post("/v1/auth/google/entrar", json=cuerpo, headers=h)


def cuenta_ligada(client) -> tuple[str, str]:
    """Cuenta que ya estaba ligada a Google: (usuarios.id, auth_id)."""
    _, uid, auth_id = nueva_cuenta(client)
    sql(
        "update usuarios set es_anonimo = false, email = $2 where id = $1::uuid",
        uid,
        f"{auth_id}@example.com",
    )
    return uid, auth_id


@pytest.fixture
def pin():
    """PIN de un solo uso; devuelve (codigo, usos_actuales)."""
    codigo = f"t{uuid.uuid4().hex[:7]}"
    sql("insert into invitaciones (codigo, usos_max, nota) values ($1, 1, 'test-google')", codigo)
    yield codigo
    sql("delete from invitaciones where nota = 'test-google'")


def usos(codigo: str) -> int:
    return fila("select usos from invitaciones where codigo = $1", codigo)["usos"]


def test_entrar_con_cuenta_conocida_no_pide_pin_y_registra_el_dispositivo(
    client, google, config_temporal
):
    config_temporal("modo_acceso", '"solo_invitacion"')
    uid, auth_id = cuenta_ligada(client)
    google["json"] = sesion_de(auth_id)
    device = f"dev-{uuid.uuid4().hex}"

    r = entrar(client, device=device)

    assert r.status_code == 200 and r.json()["refresh_token"] == "ref"
    pedido = json.loads(google["visto"][0].content)
    assert pedido == {"provider": "google", "id_token": "tok-google"}  # sin link_identity
    assert "authorization" not in google["visto"][0].headers
    d = fila(
        "select 1 from dispositivos where auth_id = $1::uuid and hash = $2",
        auth_id,
        dispositivos.hashear(device),
    )
    assert d is not None


def test_entrar_con_cuenta_de_baja_403_y_no_gasta_el_pin(client, google, config_temporal, pin):
    config_temporal("modo_acceso", '"solo_invitacion"')
    uid, auth_id = cuenta_ligada(client)
    poner_estado(uid, "baja")
    google["json"] = sesion_de(auth_id)

    r = entrar(client, codigo_invitacion=pin)

    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "cuenta_baja"
    assert usos(pin) == 0


def test_entrar_con_cuenta_fusionada_403(client, google):
    uid, auth_id = cuenta_ligada(client)
    destino, _ = cuenta_ligada(client)
    poner_estado(uid, "fusionada", destino)
    google["json"] = sesion_de(auth_id)

    r = entrar(client)

    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "cuenta_fusionada"


def test_entrar_con_google_nuevo_en_modo_abierto_crea_la_cuenta(client, google):
    auth_id = str(uuid.uuid4())
    google["json"] = sesion_de(auth_id)

    assert entrar(client).status_code == 200

    u = fila("select es_anonimo, email, alias from usuarios where auth_id = $1::uuid", auth_id)
    assert u["es_anonimo"] is False and u["email"] == f"{auth_id}@example.com"
    assert u["alias"] == f"anon-{auth_id[:6]}"


def test_entrar_con_google_nuevo_sin_pin_en_solo_invitacion_403(client, google, config_temporal):
    config_temporal("modo_acceso", '"solo_invitacion"')
    auth_id = str(uuid.uuid4())
    google["json"] = sesion_de(auth_id)

    r = entrar(client)

    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "invitacion_requerida"
    assert fila("select 1 from usuarios where auth_id = $1::uuid", auth_id) is None


def test_entrar_con_google_nuevo_y_pin_valido_gasta_el_pin(client, google, config_temporal, pin):
    config_temporal("modo_acceso", '"solo_invitacion"')
    auth_id = str(uuid.uuid4())
    google["json"] = sesion_de(auth_id)

    assert entrar(client, codigo_invitacion=pin).status_code == 200

    assert usos(pin) == 1
    p = fila("select usada_por_auth from invitaciones where codigo = $1", pin)
    assert str(p["usada_por_auth"]) == auth_id


def test_entrar_con_pin_invalido_no_crea_la_cuenta(client, google, config_temporal):
    config_temporal("modo_acceso", '"solo_invitacion"')
    auth_id = str(uuid.uuid4())
    google["json"] = sesion_de(auth_id)

    r = entrar(client, codigo_invitacion="no-existe")

    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "invitacion_invalida"
    assert fila("select 1 from usuarios where auth_id = $1::uuid", auth_id) is None


def test_entrar_con_google_nuevo_desde_un_dispositivo_con_baja_403_sin_gastar_pin(
    client, google, config_temporal, pin
):
    device = f"dev-{uuid.uuid4().hex}"
    viejo, viejo_auth = cuenta_ligada(client)
    sql(
        "insert into dispositivos (hash, auth_id) values ($1, $2::uuid)",
        dispositivos.hashear(device),
        viejo_auth,
    )
    poner_estado(viejo, "baja")
    config_temporal("modo_acceso", '"solo_invitacion"')
    google["json"] = sesion_de(str(uuid.uuid4()))

    r = entrar(client, codigo_invitacion=pin, device=device)

    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "cuenta_baja"
    assert usos(pin) == 0


def test_entrar_con_google_nuevo_con_alta_manual_403(client, google, config_temporal, pin):
    config_temporal("modo_acceso", '"alta_manual"')
    google["json"] = sesion_de(str(uuid.uuid4()))

    r = entrar(client, codigo_invitacion=pin)

    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "alta_cerrada"
    assert usos(pin) == 0


def test_entrar_con_id_token_vencido_401(client, google):
    google["status"] = 400
    google["json"] = {"error_code": "validation_failed", "msg": "Bad ID token"}
    assert entrar(client).status_code == 401


def test_las_altas_por_google_cuentan_en_el_rate_limit_de_altas(client, google, config_temporal):
    config_temporal("auth_altas_por_hora_ip", "1")
    google["json"] = sesion_de(str(uuid.uuid4()))
    assert entrar(client).status_code == 200
    google["json"] = sesion_de(str(uuid.uuid4()))
    assert entrar(client).status_code == 429
