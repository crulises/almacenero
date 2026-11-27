"""`GET /productos/{ean}/locales`: locales verificados cercanos con su último precio."""

import uuid

import pytest

from tests.conftest import make_token
from tests.db import cuerpo_carga, hacer_admin, sql

EAN = "7790070411112"
# Un punto de referencia en el Atlántico Sur, lejos de los demás tests.
LAT, LNG = -55.0, -35.0


@pytest.fixture(autouse=True, scope="module")
def _limpiar():
    yield
    sql("delete from precios where local_id in (select id from locales where nombre like 'ploc-%')")
    sql("delete from locales where nombre like 'ploc-%'")


@pytest.fixture
def admin(client):
    headers = {"Authorization": f"Bearer {make_token()}"}
    hacer_admin(client.get("/v1/me", headers=headers).json()["id"])
    return headers


def _local(client, admin, grados_lat: float = 0.0) -> str:
    """Un local verificado a `grados_lat` grados al norte del punto (1° ≈ 111 km)."""
    r = client.post(
        "/v1/locales",
        headers=admin,
        json={
            "nombre": f"ploc-{uuid.uuid4().hex[:8]}",
            "lat": LAT + grados_lat,
            "lng": LNG,
        },
    )
    assert r.status_code == 201
    return r.json()["id"]


def _precio(client, headers, local_id, precio, dias=0):
    r = client.post("/v1/precios", headers=headers, json=cuerpo_carga(local_id, EAN, precio))
    assert r.status_code == 201
    if dias:
        sql(
            "update precios set fecha = now() - make_interval(days => $2) where id = $1::uuid",
            r.json()["precio_id"],
            dias,
        )


def _locales(client, headers, con_ubicacion=True, ids=None):
    params = {"lat": LAT, "lng": LNG} if con_ubicacion else {}
    r = client.get(f"/v1/productos/{EAN}/locales", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return [v for v in r.json() if ids is None or v["local_id"] in ids]


def test_con_ubicacion_lista_locales_cercanos_con_y_sin_precio_ordenados_por_distancia(
    client, admin
):
    cerca = _local(client, admin, 0.001)  # ~110 m, sin precio
    lejos = _local(client, admin, 0.01)  # ~1,1 km, con precio
    _precio(client, admin, lejos, "150")

    res = _locales(client, admin, ids={cerca, lejos})

    assert [v["local_id"] for v in res] == [cerca, lejos]
    assert res[0]["ultimo_precio"] is None and res[0]["fecha"] is None
    assert res[1]["ultimo_precio"] == "150.00"
    assert 50 < res[0]["distancia_m"] < res[1]["distancia_m"]


def test_excluye_locales_sin_verificar(client, admin):
    local = _local(client, admin, 0.001)
    sql("update locales set verificado = false where id = $1::uuid", local)

    assert _locales(client, admin, ids={local}) == []


def test_excluye_locales_fuera_del_radio(client, admin, config_temporal):
    config_temporal("radio_precios_m", "500")
    cerca = _local(client, admin, 0.001)
    lejos = _local(client, admin, 0.02)  # ~2,2 km

    assert [v["local_id"] for v in _locales(client, admin, ids={cerca, lejos})] == [cerca]


def test_sin_ubicacion_solo_locales_con_precio_el_mas_reciente_primero(client, admin):
    sin_precio = _local(client, admin, 0.001)
    viejo = _local(client, admin, 0.002)
    nuevo = _local(client, admin, 0.003)
    _precio(client, admin, viejo, "100", dias=5)
    _precio(client, admin, nuevo, "120")

    res = _locales(client, admin, con_ubicacion=False, ids={sin_precio, viejo, nuevo})

    assert [v["local_id"] for v in res] == [nuevo, viejo]
    assert all(v["distancia_m"] is None for v in res)


def test_ultimo_precio_es_el_mas_nuevo_del_local(client, admin):
    local = _local(client, admin, 0.001)
    _precio(client, admin, local, "100", dias=10)
    _precio(client, admin, local, "130")

    (v,) = _locales(client, admin, ids={local})

    assert v["ultimo_precio"] == "130.00"


def test_lat_sin_lng_da_422(client, admin):
    r = client.get(f"/v1/productos/{EAN}/locales", headers=admin, params={"lat": LAT})
    assert r.status_code == 422
