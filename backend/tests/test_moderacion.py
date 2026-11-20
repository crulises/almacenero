"""Moderación (docs/04 §9): escalera por karma negativo y baja de cuentas.
Postgres real; el proveedor de auth, simulado solo en el refresh."""

import time
import uuid

import httpx
import jwt
import pytest

from app.config import get_settings
from app.main import app
from app.services.moderacion import escalon
from tests.conftest import make_token
from tests.db import cuerpo_carga, hacer_admin, poner_estado_sin_fecha, poner_karma, sql

EAN = "7790070411112"
LOCAL_SEED = "00000000-0000-0000-0000-000000000001"


def _nuevo(client):
    """Un usuario común nuevo: (headers, id, auth_id)."""
    auth_id = str(uuid.uuid4())
    h = {"Authorization": f"Bearer {make_token(auth_id)}"}
    return h, client.get("/v1/me", headers=h).json()["id"], auth_id


@pytest.fixture
def admin(client):
    h, uid, _ = _nuevo(client)
    hacer_admin(uid)
    return h, uid


def _cuerpo_local():
    return {"nombre": f"mod-{uuid.uuid4().hex[:6]}", "lat": -35.0, "lng": -55.0}


@pytest.fixture(autouse=True, scope="module")
def _limpiar():
    yield
    sql("delete from locales where nombre like 'mod-%'")


# ------------------------------------------------------------- la regla pura


def test_escalon_se_deduce_del_karma_y_los_umbrales():
    assert escalon(0, -5, -15) == "normal"
    assert escalon(-4, -5, -15) == "normal"
    assert escalon(-5, -5, -15) == "aviso"  # el umbral es inclusivo
    assert escalon(-14, -5, -15) == "aviso"
    assert escalon(-15, -5, -15) == "restringido"
    assert escalon(-100, -5, -15) == "restringido"


# ------------------------------------------------------------------- escalones


def test_normal_no_avisa(client):
    h, uid, _ = _nuevo(client)
    me = client.get("/v1/me", headers=h).json()
    assert me["escalon"] == "normal"
    assert me["umbral_restriccion"] == -15


def test_aviso_sigue_usando_todo(client):
    h, uid, _ = _nuevo(client)
    poner_karma(uid, -5)
    assert client.get("/v1/me", headers=h).json()["escalon"] == "aviso"
    # sigue cargando precios y locales
    r = client.post("/v1/precios", headers=h, json=cuerpo_carga(LOCAL_SEED, EAN, "1234.50"))
    assert r.status_code == 201, r.text
    assert client.post("/v1/locales", headers=h, json=_cuerpo_local()).status_code == 201
    sql("delete from precios where precio = 1234.50")


def test_restringido_no_carga_pero_consulta(client):
    h, uid, _ = _nuevo(client)
    poner_karma(uid, -15)
    assert client.get("/v1/me", headers=h).json()["escalon"] == "restringido"

    r = client.post("/v1/precios", headers=h, json=cuerpo_carga(LOCAL_SEED, EAN, "999.00"))
    assert r.status_code == 403
    assert r.json()["detail"]["codigo"] == "cuenta_restringida"
    r = client.post("/v1/locales", headers=h, json=_cuerpo_local())
    assert r.status_code == 403
    assert r.json()["detail"]["codigo"] == "cuenta_restringida"

    # consultar sigue andando
    assert client.get("/v1/locales", headers=h).status_code == 200
    assert client.get(f"/v1/productos/{EAN}", headers=h).status_code == 200
    assert client.get(f"/v1/productos/{EAN}/precios", headers=h).status_code == 200
    assert client.get(f"/v1/productos/{EAN}/precios/vigentes", headers=h).status_code == 200


def test_subir_el_karma_levanta_la_restriccion(client):
    h, uid, _ = _nuevo(client)
    poner_karma(uid, -20)
    assert (
        client.post(
            "/v1/precios", headers=h, json=cuerpo_carga(LOCAL_SEED, EAN, "5.55")
        ).status_code
        == 403
    )
    poner_karma(uid, -3)
    assert client.get("/v1/me", headers=h).json()["escalon"] == "normal"
    assert (
        client.post(
            "/v1/precios", headers=h, json=cuerpo_carga(LOCAL_SEED, EAN, "5.55")
        ).status_code
        == 201
    )
    sql("delete from precios where precio = 5.55")


def test_los_umbrales_salen_de_config(client, config_temporal):
    h, uid, _ = _nuevo(client)
    poner_karma(uid, -2)
    config_temporal("karma_umbral_aviso", "-2")
    config_temporal("karma_umbral_restriccion", "-3")
    assert client.get("/v1/me", headers=h).json()["escalon"] == "aviso"
    poner_karma(uid, -3)
    assert client.get("/v1/me", headers=h).json()["escalon"] == "restringido"


def test_un_admin_no_se_restringe_por_karma(client, admin):
    h, uid = admin
    poner_karma(uid, -500)
    assert client.get("/v1/me", headers=h).json()["escalon"] == "normal"
    r = client.post("/v1/precios", headers=h, json=cuerpo_carga(LOCAL_SEED, EAN, "6.66"))
    assert r.status_code == 201
    sql("delete from precios where precio = 6.66")


# ------------------------------------------------------------------------ baja


def _baja(client, h, uid, motivo="spam reiterado"):
    return client.post(f"/v1/admin/usuarios/{uid}/baja", headers=h, json={"motivo": motivo})


def test_baja_bloquea_todo_aunque_el_token_siga_vigente(client, admin):
    ha, _ = admin
    h, uid, _ = _nuevo(client)
    assert client.get("/v1/me", headers=h).status_code == 200

    r = _baja(client, ha, uid)
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "baja" and r.json()["baja_at"]

    # el MISMO token (vigente) deja de servir, en lectura y en escritura
    for resp in (
        client.get("/v1/me", headers=h),
        client.get("/v1/locales", headers=h),
        client.get(f"/v1/productos/{EAN}", headers=h),
        client.post("/v1/precios", headers=h, json=cuerpo_carga(LOCAL_SEED, EAN, "1.11")),
    ):
        assert resp.status_code == 403
        assert resp.json()["detail"]["codigo"] == "cuenta_baja"


def test_reactivar_vuelve_a_dejarlo_entrar(client, admin):
    ha, _ = admin
    h, uid, _ = _nuevo(client)
    _baja(client, ha, uid)
    r = client.post(
        f"/v1/admin/usuarios/{uid}/reactivar", headers=ha, json={"motivo": "fue un error"}
    )
    assert r.status_code == 200 and r.json()["estado"] == "activo" and r.json()["baja_at"] is None
    assert client.get("/v1/me", headers=h).status_code == 200


def test_baja_exige_motivo_y_deja_auditoria(client, admin):
    ha, _ = admin
    _, uid, _ = _nuevo(client)
    assert _baja(client, ha, uid, motivo="").status_code == 422
    assert _baja(client, ha, uid, motivo="ab").status_code == 422
    assert _baja(client, ha, uid, motivo="vendía precios falsos").status_code == 200
    r = client.get("/v1/admin/auditoria", headers=ha, params={"entidad": "usuario"}).json()
    fila = next(f for f in r["items"] if f["entidad_id"] == uid and f["accion"] == "usuario.baja")
    assert fila["nota"] == "vendía precios falsos"
    assert fila["antes"] == {"estado": "activo"} and fila["despues"] == {"estado": "baja"}
    client.post(f"/v1/admin/usuarios/{uid}/reactivar", headers=ha, json={"motivo": "prueba"})
    r = client.get("/v1/admin/auditoria", headers=ha, params={"entidad": "usuario"}).json()
    assert any(f["entidad_id"] == uid and f["accion"] == "usuario.reactivar" for f in r["items"])


def test_reglas_de_la_baja(client, admin):
    ha, aid = admin
    _, uid, _ = _nuevo(client)
    assert _baja(client, ha, aid).status_code == 409  # a sí mismo
    otro, otro_id, _ = _nuevo(client)
    hacer_admin(otro_id)
    assert _baja(client, ha, otro_id).status_code == 409  # a un admin
    assert _baja(client, ha, str(uuid.uuid4())).status_code == 404
    assert _baja(client, ha, uid).status_code == 200
    assert _baja(client, ha, uid).status_code == 409  # ya estaba
    client.post(f"/v1/admin/usuarios/{uid}/reactivar", headers=ha, json={"motivo": "prueba"})
    r = client.post(f"/v1/admin/usuarios/{uid}/reactivar", headers=ha, json={"motivo": "prueba"})
    assert r.status_code == 409  # ya activo


def test_un_usuario_comun_no_puede_dar_de_baja(client):
    h, _, _ = _nuevo(client)
    _, uid, _ = _nuevo(client)
    assert _baja(client, h, uid).status_code == 403


def test_el_estado_esta_protegido_por_trigger(client):
    _, uid, _ = _nuevo(client)
    with pytest.raises(Exception, match="estado no se puede modificar directamente"):
        sql("update usuarios set estado = 'baja', baja_at = now() where id = $1::uuid", uid)


def test_estado_y_fecha_son_coherentes(client):
    _, uid, _ = _nuevo(client)
    with pytest.raises(Exception, match="usuarios_baja_coherente"):
        poner_estado_sin_fecha(uid, "baja")


# --------------------------------------------------------------------- refresh


@pytest.fixture
def proveedor(client, monkeypatch):
    """GoTrue simulado: el refresh devuelve una sesión del usuario `estado['sub']`."""
    s = get_settings()
    monkeypatch.setattr(s, "auth_url", "http://auth.test/auth/v1")
    monkeypatch.setattr(s, "auth_api_key", "clave-publica")
    estado = {"sub": None}

    def handler(req: httpx.Request) -> httpx.Response:
        tok = jwt.encode({"sub": estado["sub"], "iat": int(time.time())}, "x", algorithm="HS256")
        return httpx.Response(
            200, json={"access_token": tok, "refresh_token": "ref", "expires_in": 3600}
        )

    original = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    yield estado
    app.state.http = original


def test_baja_no_puede_refrescar_la_sesion(client, admin, proveedor):
    ha, _ = admin
    _, uid, auth_id = _nuevo(client)
    proveedor["sub"] = auth_id

    r = client.post("/v1/auth/refresh", json={"refresh_token": "ref"})
    assert r.status_code == 200  # activo: renueva normal

    _baja(client, ha, uid)
    r = client.post("/v1/auth/refresh", json={"refresh_token": "ref"})
    assert r.status_code == 403
    assert r.json()["detail"]["codigo"] == "cuenta_baja"
    assert "access_token" not in r.text

    client.post(f"/v1/admin/usuarios/{uid}/reactivar", headers=ha, json={"motivo": "prueba"})
    assert client.post("/v1/auth/refresh", json={"refresh_token": "ref"}).status_code == 200


# ------------------------------------------------------------------ dispositivo


def _anonima(client, device=None):
    h = {"X-Device-Id": device} if device else {}
    return client.post("/v1/auth/anonymous", headers=h)


def test_hash_del_dispositivo():
    from app.services.dispositivos import hashear

    assert hashear(None) is None
    assert hashear("corto") is None  # no parece un ID
    assert hashear("x" * 200) is None
    a = hashear("9774D56D682E549C")
    assert a == hashear("9774d56d682e549c ")  # normaliza
    assert len(a) == 64 and "9774" not in a  # nunca el valor en claro


def test_dispositivo_de_una_cuenta_de_baja_no_crea_otra(client, admin, proveedor, config_temporal):
    config_temporal("modo_acceso", '"abierto"')
    ha, _ = admin
    device = f"dev-{uuid.uuid4().hex}"
    _, uid, auth_id = _nuevo(client)
    proveedor["sub"] = auth_id

    # El refresh asocia la cuenta (que ya existía) a su dispositivo.
    h = {"X-Device-Id": device}
    assert (
        client.post("/v1/auth/refresh", json={"refresh_token": "ref"}, headers=h).status_code == 200
    )
    assert _anonima(client, device).status_code == 200  # activa: puede haber otra cuenta

    _baja(client, ha, uid)
    r = _anonima(client, device)
    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "cuenta_baja"
    assert _anonima(client, f"dev-{uuid.uuid4().hex}").status_code == 200  # otro celular, bien
    assert _anonima(client).status_code == 200  # sin ID no hay vínculo: no rompe

    client.post(f"/v1/admin/usuarios/{uid}/reactivar", headers=ha, json={"motivo": "prueba"})
    assert _anonima(client, device).status_code == 200  # reactivada: ya no bloquea


def test_el_bloqueo_por_dispositivo_no_gasta_el_pin(client, admin, proveedor, config_temporal):
    ha, _ = admin
    device = f"dev-{uuid.uuid4().hex}"
    _, uid, auth_id = _nuevo(client)
    proveedor["sub"] = auth_id
    client.post("/v1/auth/refresh", json={"refresh_token": "ref"}, headers={"X-Device-Id": device})
    _baja(client, ha, uid)

    config_temporal("modo_acceso", '"solo_invitacion"')
    pin = client.post(
        "/v1/admin/invitaciones", headers=ha, json={"cantidad": 1, "nota": "dispositivo"}
    ).json()[0]["codigo"]
    r = client.post(
        "/v1/auth/anonymous", json={"codigo_invitacion": pin}, headers={"X-Device-Id": device}
    )
    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "cuenta_baja"
    # el PIN sigue sirviendo desde otro dispositivo
    r = client.post("/v1/auth/anonymous", json={"codigo_invitacion": pin})
    assert r.status_code == 200


def test_me_asocia_al_dispositivo_cuentas_con_sesion_vigente(client, admin, config_temporal):
    """Una cuenta que nunca pasó por alta ni refresh queda atada al abrir la app."""
    config_temporal("modo_acceso", '"abierto"')
    ha, _ = admin
    device = f"dev-{uuid.uuid4().hex}"
    h, uid, _ = _nuevo(client)
    assert client.get("/v1/me", headers={**h, "X-Device-Id": device}).status_code == 200
    _baja(client, ha, uid)
    r = _anonima(client, device)
    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "cuenta_baja"


def test_la_ficha_muestra_otras_cuentas_del_mismo_dispositivo(client, admin, proveedor):
    ha, _ = admin
    device = f"dev-{uuid.uuid4().hex}"
    _, uid1, auth1 = _nuevo(client)
    _, uid2, auth2 = _nuevo(client)
    for a in (auth1, auth2):
        proveedor["sub"] = a
        client.post(
            "/v1/auth/refresh", json={"refresh_token": "ref"}, headers={"X-Device-Id": device}
        )
    d = client.get(f"/v1/admin/usuarios/{uid1}", headers=ha).json()
    assert [c["id"] for c in d["mismo_dispositivo"]] == [uid2]
    assert d["mismo_dispositivo"][0]["estado"] == "activo"
    # una cuenta sola no tiene hermanas
    _, uid3, _ = _nuevo(client)
    assert client.get(f"/v1/admin/usuarios/{uid3}", headers=ha).json()["mismo_dispositivo"] == []


# ------------------------------------------------------------- panel / listado


def test_listado_y_ficha_muestran_estado_y_escalon(client, admin):
    ha, _ = admin
    _, u_aviso, _ = _nuevo(client)
    _, u_restr, _ = _nuevo(client)
    _, u_baja, _ = _nuevo(client)
    poner_karma(u_aviso, -6)
    poner_karma(u_restr, -40)
    _baja(client, ha, u_baja)

    def ids(**params):
        r = client.get("/v1/admin/usuarios", headers=ha, params={"limit": 200, **params})
        assert r.status_code == 200, r.text
        return {u["id"]: u for u in r.json()["items"]}

    assert ids(escalon="aviso")[u_aviso]["escalon"] == "aviso"
    assert u_aviso in ids(escalon="aviso") and u_restr not in ids(escalon="aviso")
    assert u_restr in ids(escalon="restringido") and u_aviso not in ids(escalon="restringido")
    assert u_aviso not in ids(escalon="normal") and u_baja in ids(escalon="normal")
    assert u_baja in ids(estado="baja") and u_aviso not in ids(estado="baja")

    ficha = client.get(f"/v1/admin/usuarios/{u_restr}", headers=ha).json()
    assert ficha["escalon"] == "restringido" and ficha["estado"] == "activo"


def test_la_ficha_muestra_con_que_pin_entro(client, admin):
    ha, _ = admin
    _, uid, auth_id = _nuevo(client)
    codigo = f"123{uuid.uuid4().int % 1000:03d}"
    sql(
        "insert into invitaciones (codigo, usos_max, usos, nota, usada_por_auth, usada_at) "
        "values ($1, 1, 1, 'test-mod: para Pedro', $2::uuid, now())",
        codigo,
        auth_id,
    )
    try:
        f = client.get(f"/v1/admin/usuarios/{uid}", headers=ha).json()
        assert f["invitacion_codigo"] == codigo
        assert f["invitacion_nota"] == "test-mod: para Pedro"
        _baja(client, ha, uid)
        inv = client.get("/v1/admin/invitaciones", headers=ha, params={"q": codigo}).json()
        assert inv["items"][0]["usada_por_baja"] is True
    finally:
        sql("delete from invitaciones where nota like 'test-mod%'")


def test_umbrales_en_config_se_validan(client, admin, config_temporal):
    ha, _ = admin
    put = lambda k, v: client.put(f"/v1/admin/config/{k}", headers=ha, json={"valor": v})  # noqa: E731
    config_temporal("karma_umbral_aviso", "-5")
    config_temporal("karma_umbral_restriccion", "-15")
    assert put("karma_umbral_aviso", -8).status_code == 200  # negativos: permitidos
    assert put("karma_umbral_aviso", 3).status_code == 422  # positivo: no
    assert put("karma_umbral_restriccion", -4).status_code == 422  # no puede ser mayor al aviso
    assert put("karma_umbral_restriccion", -20).status_code == 200
    assert put("karma_umbral_aviso", -25).status_code == 422  # el aviso no baja de la restricción
