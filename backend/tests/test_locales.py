"""Alta y búsqueda de locales, roles y límites, contra Postgres real."""

import random
import uuid

import pytest

from tests.conftest import make_token
from tests.db import hacer_admin, sql


def _nombre() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


def _punto() -> dict:
    """Un punto al azar en pleno Atlántico Sur: lejos de cualquier local real."""
    return {"lat": random.uniform(-60, -50), "lng": random.uniform(-40, -30)}


def _crear(client, headers, nombre=None, punto=None, **extra):
    return client.post(
        "/v1/locales",
        headers=headers,
        json={"nombre": nombre or _nombre(), **(punto or _punto()), **extra},
    )


@pytest.fixture(autouse=True, scope="module")
def _limpiar():
    yield
    sql("delete from locales where nombre like 'test-%'")


@pytest.fixture
def admin(client):
    headers = {"Authorization": f"Bearer {make_token()}"}
    hacer_admin(client.get("/v1/me", headers=headers).json()["id"])
    return headers


# ------------------------------------------------------------------ alta
def test_un_usuario_crea_un_local_sin_verificar(client, auth):
    r = _crear(client, auth, direccion="  Calle 1  ")
    assert r.status_code == 201
    local = r.json()
    assert local["verificado"] is False
    assert local["direccion"] == "Calle 1"
    assert client.get("/v1/locales", headers=auth).status_code == 200


def test_con_el_alta_cerrada_un_usuario_no_crea_locales(client, auth, config_temporal):
    config_temporal("alta_locales_abierta", "false")
    assert _crear(client, auth).status_code == 403


def test_un_admin_crea_locales_verificados_aun_con_el_alta_cerrada(client, admin, config_temporal):
    config_temporal("alta_locales_abierta", "false")
    r = _crear(client, admin)
    assert r.status_code == 201
    assert r.json()["verificado"] is True


def test_limite_diario_de_locales_nuevos(client, auth, config_temporal):
    config_temporal("max_locales_por_dia", "2")
    assert _crear(client, auth).status_code == 201
    assert _crear(client, auth).status_code == 201
    r = _crear(client, auth)
    assert r.status_code == 429
    # el límite es por usuario
    otro = {"Authorization": f"Bearer {make_token()}"}
    assert _crear(client, otro).status_code == 201


def test_datos_invalidos(client, auth):
    assert _crear(client, auth, nombre="   ").status_code == 422
    assert _crear(client, auth, punto={"lat": 91, "lng": 0}).status_code == 422
    assert _crear(client, auth, punto={"lat": 0, "lng": 181}).status_code == 422


# ----------------------------------------------------------- anti-duplicados
def test_mismo_nombre_en_el_mismo_lugar_es_duplicado(client, auth):
    punto, nombre = _punto(), _nombre()
    primero = _crear(client, auth, nombre, punto).json()

    r = _crear(client, auth, nombre, punto)

    assert r.status_code == 409
    assert r.json()["detail"]["codigo"] == "local_duplicado"
    assert r.json()["detail"]["local"]["id"] == primero["id"]


def test_locales_contiguos_con_otro_nombre_no_son_duplicado(client, auth):
    punto = _punto()
    assert _crear(client, auth, _nombre(), punto).status_code == 201
    assert _crear(client, auth, _nombre(), punto).status_code == 201


def test_mismo_nombre_pero_lejos_no_es_duplicado(client, auth):
    nombre = _nombre()
    assert _crear(client, auth, nombre, _punto()).status_code == 201
    assert _crear(client, auth, nombre, _punto()).status_code == 201


# -------------------------------------------------------------------- cerca
def test_locales_cerca_ordenados_por_distancia(client, auth):
    p = _punto()
    cerca = _crear(client, auth, _nombre(), p).json()
    # ~60 m al norte (0,0005° de latitud ≈ 55 m)
    algo_mas = _crear(client, auth, _nombre(), {"lat": p["lat"] + 0.0005, "lng": p["lng"]}).json()
    lejos = _crear(client, auth, _nombre(), {"lat": p["lat"] + 0.01, "lng": p["lng"]}).json()

    r = client.get("/v1/locales/cerca", params={**p, "radio_m": 100}, headers=auth)

    assert r.status_code == 200
    ids = [x["id"] for x in r.json()]
    assert ids == [cerca["id"], algo_mas["id"]]
    assert lejos["id"] not in ids
    assert r.json()[0]["distancia_m"] < 1
    assert 40 < r.json()[1]["distancia_m"] < 70


def test_locales_cerca_usa_el_geofence_por_defecto(client, auth):
    p = _punto()
    _crear(client, auth, _nombre(), p)
    # ~220 m: fuera de los 150 m del geofence
    _crear(client, auth, _nombre(), {"lat": p["lat"] + 0.002, "lng": p["lng"]})

    r = client.get("/v1/locales/cerca", params=p, headers=auth)

    assert len(r.json()) == 1


def test_locales_cerca_valida_parametros(client, auth):
    assert client.get("/v1/locales/cerca", params={"lat": 0}, headers=auth).status_code == 422
    r = client.get("/v1/locales/cerca", params={"lat": 0, "lng": 0, "radio_m": 99999}, headers=auth)
    assert r.status_code == 422


# ----------------------------------------------------------------- verificar
def test_solo_un_admin_verifica(client, auth, admin):
    local = _crear(client, auth).json()

    assert client.post(f"/v1/locales/{local['id']}/verificar", headers=auth).status_code == 403
    r = client.post(f"/v1/locales/{local['id']}/verificar", headers=admin)
    assert r.status_code == 200
    assert r.json()["verificado"] is True


def test_verificar_un_local_inexistente(client, admin):
    r = client.post(f"/v1/locales/{uuid.uuid4()}/verificar", headers=admin)
    assert r.status_code == 404
