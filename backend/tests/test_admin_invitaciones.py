"""PINs de invitación de un solo uso, administrados desde /v1/admin/invitaciones.
Postgres real; el proveedor de auth se simula (devuelve un JWT con `sub` real)."""

import re
import uuid

import httpx
import pytest

from app.config import get_settings
from app.main import app
from tests.conftest import make_token
from tests.db import hacer_admin, sql

NOTA = "t-pin"


@pytest.fixture(autouse=True, scope="module")
def _limpiar():
    yield
    sql("delete from invitaciones where nota like 't-pin%'")


@pytest.fixture
def admin(client):
    h = {"Authorization": f"Bearer {make_token()}"}
    hacer_admin(client.get("/v1/me", headers=h).json()["id"])
    return h


@pytest.fixture
def proveedor(client, monkeypatch, config_temporal):
    """El proveedor devuelve un token cuyo `sub` es un usuario nuevo, como GoTrue."""
    config_temporal("modo_acceso", '"solo_invitacion"')
    config_temporal("auth_altas_por_hora_ip", "1000")
    s = get_settings()
    monkeypatch.setattr(s, "auth_url", "http://auth.test/auth/v1")
    monkeypatch.setattr(s, "auth_api_key", "clave-publica")
    nuevos: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        sub = str(uuid.uuid4())
        nuevos.append(sub)
        return httpx.Response(
            200, json={"access_token": make_token(sub), "refresh_token": "r", "expires_in": 3600}
        )

    original = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    yield nuevos
    app.state.http = original


def _crear(client, admin, **cuerpo):
    cuerpo.setdefault("nota", NOTA)
    return client.post("/v1/admin/invitaciones", headers=admin, json=cuerpo)


def _alta(client, pin):
    return client.post("/v1/auth/anonymous", json={"codigo_invitacion": pin})


def _ficha(client, admin, pin):
    items = client.get(f"/v1/admin/invitaciones?q={pin}", headers=admin).json()["items"]
    assert len(items) == 1
    return items[0]


def test_el_admin_crea_un_lote_de_pines_de_6_digitos_de_un_solo_uso(client, admin):
    r = _crear(client, admin, cantidad=5, nota="t-pin lote", vigencia_horas=2)
    assert r.status_code == 201
    pines = r.json()
    assert len(pines) == 5
    assert len({p["codigo"] for p in pines}) == 5  # distintos entre sí
    for p in pines:
        assert re.fullmatch(r"\d{6}", p["codigo"])
        assert (p["usos_max"], p["usos"], p["estado"]) == (1, 0, "disponible")
        assert p["nota"] == "t-pin lote"
        assert p["vence"] is not None


def test_sin_vigencia_el_pin_no_vence(client, admin):
    [pin] = _crear(client, admin, vigencia_horas=None).json()
    assert pin["vence"] is None


def test_limites_del_lote(client, admin):
    assert _crear(client, admin, cantidad=0).status_code == 422
    assert _crear(client, admin, cantidad=101).status_code == 422
    assert _crear(client, admin, vigencia_horas=0).status_code == 422


def test_un_usuario_comun_no_ve_ni_crea_pines(client, auth):
    assert client.get("/v1/admin/invitaciones", headers=auth).status_code == 403
    assert client.post("/v1/admin/invitaciones", headers=auth, json={}).status_code == 403


def test_un_pin_lo_usa_una_sola_persona_una_sola_vez(client, admin, proveedor):
    [pin] = _crear(client, admin, nota="t-pin uso").json()
    assert _alta(client, pin["codigo"]).status_code == 200
    r = _alta(client, pin["codigo"])
    assert r.status_code == 403
    assert r.json()["detail"]["codigo"] == "invitacion_invalida"
    assert len(proveedor) == 1  # el segundo intento ni llegó a crear un usuario


def test_el_panel_muestra_el_pin_usado_y_quien_lo_uso(client, admin, proveedor):
    [pin] = _crear(client, admin, nota="t-pin quien").json()
    sesion = _alta(client, pin["codigo"]).json()
    # el usuario aparece en `usuarios` al hacer su primer pedido autenticado
    yo = client.get("/v1/me", headers={"Authorization": f"Bearer {sesion['access_token']}"}).json()

    f = _ficha(client, admin, pin["codigo"])
    assert f["estado"] == "usada"
    assert f["usada_at"] is not None
    assert f["usada_por_id"] == yo["id"]
    assert f["usada_por_alias"] == yo["alias"]
    assert f["creada_por_alias"] is not None


def test_filtro_por_estado(client, admin, proveedor):
    [libre, gastado] = _crear(client, admin, cantidad=2, nota="t-pin filtro").json()
    assert _alta(client, gastado["codigo"]).status_code == 200

    def codigos(estado):
        r = client.get(f"/v1/admin/invitaciones?estado={estado}&q=t-pin filtro", headers=admin)
        return {i["codigo"] for i in r.json()["items"]}

    assert codigos("disponible") == {libre["codigo"]}
    assert codigos("usada") == {gastado["codigo"]}
    assert codigos("vencida") == set()
    assert client.get("/v1/admin/invitaciones?estado=otro", headers=admin).status_code == 422


def test_un_pin_vencido_no_entra_y_el_panel_lo_marca(client, admin, proveedor):
    [pin] = _crear(client, admin, nota="t-pin vencido").json()
    sql(
        "update invitaciones set vence = now() - interval '1 minute' where codigo = $1",
        pin["codigo"],
    )
    assert _ficha(client, admin, pin["codigo"])["estado"] == "vencida"
    assert _alta(client, pin["codigo"]).status_code == 403


def test_si_el_proveedor_falla_el_pin_sigue_disponible(client, admin, proveedor):
    [pin] = _crear(client, admin, nota="t-pin falla").json()
    original = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    try:
        assert _alta(client, pin["codigo"]).status_code == 502
    finally:
        app.state.http = original
    f = _ficha(client, admin, pin["codigo"])
    assert (f["estado"], f["usos"], f["usada_at"]) == ("disponible", 0, None)
    assert _alta(client, pin["codigo"]).status_code == 200


def test_revocar_un_pin_disponible_lo_borra_y_deja_rastro(client, admin):
    [pin] = _crear(client, admin, nota="t-pin revocar").json()
    assert client.delete(f"/v1/admin/invitaciones/{pin['id']}", headers=admin).status_code == 204
    assert (
        client.get(f"/v1/admin/invitaciones?q={pin['codigo']}", headers=admin).json()["total"] == 0
    )
    log = client.get(
        f"/v1/admin/auditoria?entidad=invitacion&entidad_id={pin['id']}", headers=admin
    )
    assert [a["accion"] for a in log.json()["items"]] == ["invitacion.revocar", "invitacion.crear"]


def test_un_pin_usado_no_se_puede_borrar(client, admin, proveedor):
    [pin] = _crear(client, admin, nota="t-pin usado").json()
    _alta(client, pin["codigo"])
    r = client.delete(f"/v1/admin/invitaciones/{pin['id']}", headers=admin)
    assert r.status_code == 409
    assert _ficha(client, admin, pin["codigo"])["estado"] == "usada"


def test_revocar_inexistente_404(client, admin):
    assert client.delete(f"/v1/admin/invitaciones/{uuid.uuid4()}", headers=admin).status_code == 404


def test_un_pin_revocado_ya_no_entra(client, admin, proveedor):
    [pin] = _crear(client, admin, nota="t-pin revocado").json()
    client.delete(f"/v1/admin/invitaciones/{pin['id']}", headers=admin)
    assert _alta(client, pin["codigo"]).status_code == 403
