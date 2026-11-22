"""Errores que explican la regla violada (docs/04 §10-E): nada de «Failed to fetch» ni de 500
mudos, y el texto es editable desde el panel. Contra Postgres real."""

import asyncio
import json
from types import SimpleNamespace

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app import errores
from app.main import app
from app.services import reglas
from tests.db import sql
from tests.test_sugerencias import (  # noqa: F401
    EAN,
    _producto,
    _productos,
    _sugerir,
    admin,
    moderador,
)

CLAVE = reglas.CLAVE_CONFIG


@pytest.fixture(autouse=True)
def _limpio():
    sql("delete from config where clave = $1", CLAVE)
    yield
    sql("delete from config where clave = $1", CLAVE)


def _sugerencia_rota(client, h):
    """Una sugerencia que la base no va a admitir al aplicarla (tamaño 0 viejo, guardado
    antes de que existiera la validación)."""
    s = _sugerir(client, h, nombre="Desinfectante Ambiental")
    sql(
        "update sugerencias_catalogo set cambios = cambios || "
        '\'{"tamano_valor": 0, "tamano_unidad": "ml"}\' where id = $1::uuid',
        s.json()["id"],
    )
    return s.json()["id"]


def test_un_dato_que_la_base_rechaza_explica_la_regla(client, moderador, admin):  # noqa: F811
    sid = _sugerencia_rota(client, moderador)
    r = client.post(f"/v1/admin/sugerencias/{sid}/aprobar", headers=admin)
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["codigo"] == "dato_invalido" and d["como_resolver"] and d["titulo"]
    assert d["campos"] == [{"campo": "tamano_valor", "problema": "tiene que ser mayor a 0"}]
    assert _producto()["nombre"] == "Desinfect Amb Origin"  # nada quedó a medias


def test_mensaje_editable_desde_el_panel(client, moderador, admin):  # noqa: F811
    r = client.put(
        "/v1/admin/reglas/dato_invalido", headers=admin, json={"mensaje": "  Dato mal, che  "}
    )
    assert r.status_code == 200 and r.json()["editado"] and r.json()["mensaje"] == "Dato mal, che"
    sid = _sugerencia_rota(client, moderador)
    d = client.post(f"/v1/admin/sugerencias/{sid}/aprobar", headers=admin).json()["detail"]
    assert d["mensaje"] == "Dato mal, che"
    assert d["codigo"] == "dato_invalido"  # el código no se edita
    # vacío = volver al por defecto
    r = client.put("/v1/admin/reglas/dato_invalido", headers=admin, json={"mensaje": ""})
    assert not r.json()["editado"] and r.json()["mensaje"] == r.json()["mensaje_default"]
    lista = client.get("/v1/admin/reglas", headers=admin).json()
    assert {x["codigo"] for x in lista} == set(reglas.REGLAS)
    assert sql("select 1 from auditoria_admin where accion = 'reglas.mensaje'") is not None


def test_editar_mensajes_valida(client, moderador, admin):  # noqa: F811
    assert (
        client.put("/v1/admin/reglas/nada", headers=admin, json={"mensaje": "x"}).status_code == 404
    )
    largo = client.put("/v1/admin/reglas/pack_minimo", headers=admin, json={"mensaje": "x" * 401})
    assert largo.status_code == 422
    # un moderador no edita mensajes
    assert (
        client.put(
            "/v1/admin/reglas/pack_minimo", headers=moderador, json={"mensaje": "x"}
        ).status_code
        == 403
    )
    # y la clave no aparece como un valor suelto de configuración
    claves = {c["clave"] for c in client.get("/v1/admin/config", headers=admin).json()}
    assert CLAVE not in claves
    assert (
        client.put(f"/v1/admin/config/{CLAVE}", headers=admin, json={"valor": {}}).status_code
        == 422
    )


def test_en_masa_la_falla_dice_la_regla(client, moderador, admin):  # noqa: F811
    sid = _sugerencia_rota(client, moderador)
    r = client.post(
        "/v1/admin/sugerencias/resolver", headers=admin, json={"ids": [sid], "accion": "aprobar"}
    )
    assert r.status_code == 200, r.text
    falla = r.json()["fallidas"][0]["error"]
    assert "mayor a 0" in falla and "tamano_valor" in falla


def test_regla_de_clasifica_los_errores_de_postgres():
    class Falso(Exception):
        constraint_name = "productos_canonicos_pack_cantidad_check"

    assert reglas.regla_de(Falso()).codigo == "pack_minimo"
    Falso.constraint_name = "otra_cosa"
    assert reglas.regla_de(Falso()).codigo == "dato_invalido"
    assert all(r.mensaje and r.como_resolver for r in reglas.REGLAS.values())
    assert set(reglas.POR_CONSTRAINT.values()) <= set(reglas.REGLAS)


def test_un_error_inesperado_responde_con_referencia_y_cors(client):
    """Antes salía como 500 sin cabeceras CORS: el navegador lo mostraba como «Failed to
    fetch». Ahora lleva el detalle y las cabeceras."""

    @app.get("/v1/_boom")
    async def boom():
        raise RuntimeError("secreto interno")

    try:
        c = TestClient(app, raise_server_exceptions=False)  # sin lifespan: pool del `client`
        origen = "http://localhost:8080"
        r = c.get("/v1/_boom", headers={"Origin": origen})
    finally:
        app.router.routes = [x for x in app.router.routes if getattr(x, "path", "") != "/v1/_boom"]
    assert r.status_code == 500
    d = r.json()["detail"]
    assert d["codigo"] == "error_interno" and len(d["referencia"]) == 8
    assert "secreto" not in r.text
    assert r.headers.get("access-control-allow-origin") == origen


def test_una_violacion_de_la_base_responde_422_con_la_regla():
    """El check de pack (> 1) que antes salía como 500 mudo ahora explica la regla."""
    with pytest.raises(asyncpg.CheckViolationError) as e:
        sql(
            "insert into productos_canonicos (ean, nombre, origen, pack_cantidad) "
            "values ('7790000000999', 'x', 'manual', 1)"
        )
    pedido = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(pool=None)),  # sin pool: mensajes por defecto
        method="GET",
        url=SimpleNamespace(path="/v1/x"),
        headers={"origin": "http://localhost:8080"},
    )
    r = asyncio.run(errores.violacion_de_integridad(pedido, e.value))
    d = json.loads(r.body)["detail"]
    assert r.status_code == 422
    assert d["codigo"] == "pack_minimo" and "2" in d["mensaje"] and d["como_resolver"]
    assert d["restriccion"] == "productos_canonicos_pack_cantidad_check"
    assert r.headers["access-control-allow-origin"] == "http://localhost:8080"
