"""Avisos de catálogo (feedback sin karma) y ayuda de estándares. Postgres real."""

import json

from app.services.estandares import ESTANDARES
from tests.conftest import make_token
from tests.db import poner_karma, sql
from tests.test_admin import _consulta

EAN = "7790000000086"


def _usuario(client):
    h = {"Authorization": f"Bearer {make_token()}"}
    return h, client.get("/v1/me", headers=h).json()["id"]


def _aviso(uid):
    sql(
        "insert into productos_canonicos (ean, nombre, origen) values ($1, 'Aceite Girasol', "
        "'manual') on conflict do nothing",
        EAN,
    )
    sql(
        "insert into avisos_catalogo (usuario_id, ean, tipo, estandares, antes, despues) values "
        "($1::uuid, $2, 'nombre_ajustado', '{nombre,marca}', $3::jsonb, $4::jsonb)",
        uid,
        EAN,
        json.dumps({"nombre": "Aceite Cocinero Girasol 900 ml"}),
        json.dumps({"nombre": "Aceite Girasol"}),
    )


def test_la_ayuda_lista_los_estandares(client, auth):
    r = client.get("/v1/ayuda/estandares", headers=auth)
    assert r.status_code == 200
    assert [e["id"] for e in r.json()] == [e.id for e in ESTANDARES]
    assert client.get("/v1/ayuda/estandares").status_code in (401, 403)


def test_el_aviso_explica_el_porque_y_no_toca_el_karma(client):
    h, uid = _usuario(client)
    poner_karma(uid, 4)
    _aviso(uid)
    try:
        avisos = client.get("/v1/me/avisos", headers=h).json()
        assert len(avisos) == 1
        a = avisos[0]
        assert a["leido"] is False and a["despues"]["nombre"] == "Aceite Girasol"
        assert [e["id"] for e in a["estandares"]] == ["nombre", "marca"]
        assert "no cumplía los estándares de carga" in a["mensaje"]
        assert "no afecta tu karma" in a["mensaje"]
        assert client.get("/v1/me", headers=h).json()["karma"] == 4
        # marcar leídos
        assert client.post("/v1/me/avisos/leidos", headers=h).status_code == 204
        assert client.get("/v1/me/avisos?no_leidos=true", headers=h).json() == []
        assert len(client.get("/v1/me/avisos", headers=h).json()) == 1
    finally:
        sql("delete from avisos_catalogo where usuario_id = $1::uuid", uid)
        sql("delete from productos_canonicos where ean = $1", EAN)


def test_cada_uno_ve_solo_sus_avisos(client):
    h1, u1 = _usuario(client)
    h2, _ = _usuario(client)
    _aviso(u1)
    try:
        assert client.get("/v1/me/avisos", headers=h2).json() == []
        assert (
            _consulta("select count(*) c from avisos_catalogo where usuario_id = $1::uuid", u1)[0][
                "c"
            ]
            == 1
        )
    finally:
        sql("delete from avisos_catalogo where usuario_id = $1::uuid", u1)
        sql("delete from productos_canonicos where ean = $1", EAN)
