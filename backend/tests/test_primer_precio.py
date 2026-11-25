"""Bonus de karma por ser el primero en cargar un producto (corte 20), contra Postgres real."""

import random
import uuid

import pytest

from tests.conftest import make_token
from tests.db import cuerpo_carga, hacer_admin, sql

EAN = "7790000000444"  # lo usa solo este módulo: arranca sin precios


@pytest.fixture(autouse=True)
def _producto():
    sql(
        "insert into productos_canonicos (ean, nombre, origen) values ($1, 'Primer precio', "
        "'manual') on conflict do nothing",
        EAN,
    )
    sql(
        "delete from precios where producto_canonico_id in "
        "(select id from productos_canonicos where ean = $1)",
        EAN,
    )
    yield
    sql(
        "delete from precios where producto_canonico_id in "
        "(select id from productos_canonicos where ean = $1)",
        EAN,
    )
    sql("delete from locales where nombre like 'pri-%'")


def _usuario(client, admin=False):
    h = {"Authorization": f"Bearer {make_token()}"}
    uid = client.get("/v1/me", headers=h).json()["id"]
    if admin:
        hacer_admin(uid)
    return h


def _local(client, adm) -> str:
    r = client.post(
        "/v1/locales",
        headers=adm,
        json={
            "nombre": f"pri-{uuid.uuid4().hex[:8]}",
            "lat": random.uniform(-60, -50),
            "lng": random.uniform(-40, -30),
        },
    )
    return r.json()["id"]


def _cargar(client, h, local, precio):
    r = client.post("/v1/precios", headers=h, json=cuerpo_carga(local, EAN, precio))
    assert r.status_code == 201
    return r.json()


def test_el_primero_en_cargar_el_producto_suma_el_bonus(client):
    adm = _usuario(client, admin=True)
    local = _local(client, adm)

    r = _cargar(client, adm, local, "100")

    assert r["primer_precio"] is True
    assert r["karma_sumado"] == 1 + 5  # karma_por_carga + karma_primer_precio (default 5)


def test_el_bonus_se_da_una_sola_vez_por_producto(client):
    adm = _usuario(client, admin=True)
    local = _local(client, adm)
    otro_local = _local(client, adm)

    _cargar(client, adm, local, "100")
    segundo = _cargar(client, adm, otro_local, "120")
    otra_persona = _cargar(client, _usuario(client, admin=True), local, "130")

    assert segundo["primer_precio"] is False and segundo["karma_sumado"] == 1
    assert otra_persona["primer_precio"] is False and otra_persona["karma_sumado"] == 1


def test_repetir_el_mismo_precio_no_suma_ni_bonus(client):
    adm = _usuario(client, admin=True)
    local = _local(client, adm)
    _cargar(client, adm, local, "100")

    repetido = _cargar(client, adm, local, "100")

    assert repetido["karma_sumado"] == 0 and repetido["primer_precio"] is False


def test_el_bonus_sale_de_config(client):
    sql("delete from config where clave = 'karma_primer_precio' and rubro is null")
    sql("insert into config (clave, valor, rubro) values ('karma_primer_precio', '10', null)")
    try:
        adm = _usuario(client, admin=True)
        r = _cargar(client, adm, _local(client, adm), "100")
        assert r["karma_sumado"] == 1 + 10
    finally:
        sql("delete from config where clave = 'karma_primer_precio' and rubro is null")
