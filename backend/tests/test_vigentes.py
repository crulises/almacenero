"""Precios vigentes (el último por local) y su frescura, contra Postgres real."""

import random
import uuid

import pytest

from tests.conftest import make_token
from tests.db import cuerpo_carga, hacer_admin, sql

EAN = "7790070411112"


@pytest.fixture(autouse=True, scope="module")
def _limpiar():
    yield
    sql("delete from precios where local_id in (select id from locales where nombre like 'vig-%')")
    sql("delete from locales where nombre like 'vig-%'")


@pytest.fixture
def admin(client):
    headers = {"Authorization": f"Bearer {make_token()}"}
    hacer_admin(client.get("/v1/me", headers=headers).json()["id"])
    return headers


def _local(client, admin) -> str:
    r = client.post(
        "/v1/locales",
        headers=admin,
        json={
            "nombre": f"vig-{uuid.uuid4().hex[:8]}",
            "lat": random.uniform(-60, -50),
            "lng": random.uniform(-40, -30),
        },
    )
    return r.json()["id"]


def _precio(client, headers, local_id, precio, dias=0, ean=EAN):
    """Carga un precio y lo «envejece» `dias` días."""
    r = client.post("/v1/precios", headers=headers, json=cuerpo_carga(local_id, ean, precio))
    assert r.status_code == 201
    if dias:
        sql(
            "update precios set fecha = now() - make_interval(days => $2) where id = $1::uuid",
            r.json()["precio_id"],
            dias,
        )


def _vigentes(client, headers, ean=EAN, locales=None):
    r = client.get(f"/v1/productos/{ean}/precios/vigentes", headers=headers)
    assert r.status_code == 200
    todos = r.json()
    return [v for v in todos if locales is None or v["local_id"] in locales]


def test_un_precio_por_local_el_mas_nuevo(client, admin):
    local = _local(client, admin)
    _precio(client, admin, local, "100", dias=10)
    _precio(client, admin, local, "150", dias=0)

    vigentes = _vigentes(client, admin, locales={local})

    assert [v["precio"] for v in vigentes] == ["150.00"]
    assert vigentes[0]["edad_dias"] == 0


def test_trae_ubicacion_y_nombre_del_local(client, admin):
    local = _local(client, admin)
    _precio(client, admin, local, "100")

    v = _vigentes(client, admin, locales={local})[0]

    assert v["local_nombre"].startswith("vig-")
    assert -60 <= v["lat"] <= -50
    assert -40 <= v["lng"] <= -30
    assert v["local_verificado"] is True


def test_ordenados_del_mas_barato_al_mas_caro(client, admin):
    a, b, c = (_local(client, admin) for _ in range(3))
    _precio(client, admin, a, "300")
    _precio(client, admin, b, "100")
    _precio(client, admin, c, "200")

    vigentes = _vigentes(client, admin, locales={a, b, c})

    assert [v["precio"] for v in vigentes] == ["100.00", "200.00", "300.00"]


@pytest.mark.parametrize(
    ("dias", "frescura", "vencido"),
    [
        (0, "verde", False),
        (7, "verde", False),
        (15, "amarillo", False),
        (25, "rojo", False),
        (45, "rojo", True),
    ],
)
def test_frescura_segun_la_antiguedad(client, admin, dias, frescura, vencido):
    local = _local(client, admin)
    _precio(client, admin, local, "100", dias=dias)

    v = _vigentes(client, admin, locales={local})[0]

    assert v["edad_dias"] == dias
    assert v["frescura"] == frescura
    assert v["vencido"] is vencido


def test_producto_sin_precios_devuelve_lista_vacia(client, auth):
    r = client.get("/v1/productos/7799999999999/precios/vigentes", headers=auth)
    assert r.status_code == 200
    assert r.json() == []


def _local_en(client, admin, lat, lng) -> str:
    r = client.post(
        "/v1/locales",
        headers=admin,
        json={"nombre": f"vig-{uuid.uuid4().hex[:8]}", "lat": lat, "lng": lng},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_con_ubicacion_solo_trae_los_locales_dentro_del_radio(client, admin):
    # Un punto del Atlántico Sur, como en los otros tests; ~1,1 km por 0,01° de lat.
    lat, lng = random.uniform(-60, -50), random.uniform(-40, -30)
    cerca = _local_en(client, admin, lat + 0.01, lng)  # ~1,1 km
    lejos = _local_en(client, admin, lat + 0.2, lng)  # ~22 km
    _precio(client, admin, cerca, "100")
    _precio(client, admin, lejos, "50")

    r = client.get(
        f"/v1/productos/{EAN}/precios/vigentes",
        params={"lat": lat, "lng": lng},
        headers=admin,
    )

    assert r.status_code == 200
    ids = [v["local_id"] for v in r.json() if v["local_id"] in (cerca, lejos)]
    assert ids == [cerca]  # el de 22 km queda fuera del radio por defecto (5 km)
    assert 1000 < r.json()[0]["distancia_m"] < 1300


def test_el_radio_se_puede_ampliar(client, admin):
    lat, lng = random.uniform(-60, -50), random.uniform(-40, -30)
    lejos = _local_en(client, admin, lat + 0.2, lng)
    _precio(client, admin, lejos, "50")

    r = client.get(
        f"/v1/productos/{EAN}/precios/vigentes",
        params={"lat": lat, "lng": lng, "radio_m": 30000},
        headers=admin,
    )

    assert lejos in [v["local_id"] for v in r.json()]


def test_sin_ubicacion_trae_todos_y_sin_distancia(client, admin):
    local = _local(client, admin)
    _precio(client, admin, local, "100")

    v = _vigentes(client, admin, locales={local})[0]

    assert v["distancia_m"] is None


def test_lat_sin_lng_es_invalido(client, admin):
    r = client.get(f"/v1/productos/{EAN}/precios/vigentes", params={"lat": -34}, headers=admin)
    assert r.status_code == 422
