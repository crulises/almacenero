"""Calidad del catálogo (Doc 7): lo descartado no se muestra, el panel filtra y cuenta por
estado, y corregir a mano recalcula el puntaje. Contra Postgres real."""

import pytest

from tests.db import cuerpo_carga, hacer_admin, sql
from tests.test_admin import _consulta, _local

EAN_DESCARTADO = "7790000000024"
EAN_DUDOSO = "7790000000031"


@pytest.fixture(autouse=True)
def _productos():
    def limpiar():
        sql("delete from productos_canonicos where ean in ($1, $2)", EAN_DESCARTADO, EAN_DUDOSO)

    limpiar()
    sql(
        "insert into productos_canonicos (ean, nombre, origen, calidad, estado_calidad, "
        "calidad_motivos) values ($1, 'Fanta', 'off', 40, 'descartado', "
        "'{sin_marca,sin_tamano,nombre_corto,muy_incompleto}')",
        EAN_DESCARTADO,
    )
    sql(
        "insert into productos_canonicos (ean, nombre, marca, origen, calidad, estado_calidad, "
        "calidad_motivos, pack_cantidad, presentacion) values ($1, 'Desinfect Amb Origin', "
        "'Lysoform', 'sepa', 40, 'dudoso', '{abreviado,sin_tamano}', 6, 'botella')",
        EAN_DUDOSO,
    )
    yield
    limpiar()


@pytest.fixture
def admin(client, auth):
    hacer_admin(client.get("/v1/me", headers=auth).json()["id"])
    return auth


def test_un_descartado_no_se_encuentra_en_la_app(client, auth):
    assert client.get(f"/v1/productos/{EAN_DESCARTADO}", headers=auth).status_code == 404
    d = client.get(f"/v1/productos/{EAN_DUDOSO}", headers=auth).json()
    assert (d["pack_cantidad"], d["presentacion"]) == (6, "botella")  # un dudoso sí se ve


def test_no_se_puede_cargar_precio_a_un_descartado(client, auth):
    lid = _local(verificado=True)
    r = client.post("/v1/precios", headers=auth, json=cuerpo_carga(lid, EAN_DESCARTADO, "100"))
    assert r.status_code == 404
    sql("delete from locales where id = $1::uuid", lid)


def test_el_listado_filtra_y_ordena_por_calidad(client, admin):
    r = client.get("/v1/admin/productos?estado=descartado&q=77900000000", headers=admin)
    assert [p["ean"] for p in r.json()["items"]] == [EAN_DESCARTADO]
    r = client.get("/v1/admin/productos?motivo=abreviado&q=7790000000031", headers=admin)
    assert [p["ean"] for p in r.json()["items"]] == [EAN_DUDOSO]
    d = r.json()["items"][0]
    assert (d["estado_calidad"], d["calidad"], d["calidad_motivos"]) == (
        "dudoso",
        40,
        ["abreviado", "sin_tamano"],
    )
    orden = client.get("/v1/admin/productos?orden=calidad&limit=2", headers=admin).json()
    assert orden["items"][0]["estado_calidad"] == "dudoso"  # dudosos primero
    assert client.get("/v1/admin/productos?estado=nada", headers=admin).status_code == 422


def test_tablero_cuenta_por_estado_y_motivo(client, admin):
    t = client.get("/v1/admin/catalogo/calidad", headers=admin).json()
    assert t["total"] == sum(t["por_estado"].values())
    assert t["por_estado"]["dudoso"] >= 1 and t["por_estado"]["descartado"] >= 1
    assert t["por_motivo"]["abreviado"] >= 1
    assert set(t["por_estado"]) >= {"completo", "parcial", "dudoso", "descartado", "sin_evaluar"}


def test_el_tablero_es_solo_de_admin(client, auth):
    assert client.get("/v1/admin/catalogo/calidad", headers=auth).status_code == 403


def test_corregir_a_mano_recalcula_la_calidad(client, admin):
    pid = str(_consulta("select id from productos_canonicos where ean = $1", EAN_DUDOSO)[0]["id"])
    r = client.patch(
        f"/v1/admin/productos/{pid}",
        headers=admin,
        json={
            "nombre": "Desinfectante Ambiental Original",
            "tamano_valor": "380",
            "tamano_unidad": "ml",
        },
    )
    assert r.status_code == 200, r.text
    d = r.json()
    # nombre y tamaño corregidos por una persona: `abreviado` y `sin_tamano` ya no cuentan
    assert (d["estado_calidad"], d["calidad_motivos"]) == ("completo", [])
    assert d["calidad"] == 95  # 40 + 10 nombre + 20 marca + 20 tamaño + 5 presentación
    # sin marca y con una palabra: parcial (el tamaño sigue); un nombre que lo bloqueó la persona
    # no se vuelve a juzgar como «corto» por abreviado, pero sí cuenta sus palabras
    r = client.patch(
        f"/v1/admin/productos/{pid}", headers=admin, json={"marca": None, "nombre": "Aceite"}
    )
    assert (r.json()["estado_calidad"], r.json()["calidad"]) == ("parcial", 65)
