"""Moderador y cola de sugerencias (docs/04 §10-D): propone, el admin aprueba o rechaza.
Alta simple y corrección directa del panel. Contra Postgres real."""

from types import SimpleNamespace

import pytest

from app.services.permisos import puede
from tests.conftest import make_token
from tests.db import hacer_rol, poner_karma, sql
from tests.test_admin import _consulta

EAN = "7790000000055"  # producto que existe (dudoso)
EAN_ALTA = "7790000000062"  # no existe: se da de alta


@pytest.fixture(autouse=True)
def _productos():
    def limpiar():
        sql("delete from sugerencias_catalogo where ean in ($1, $2)", EAN, EAN_ALTA)
        sql("delete from productos_canonicos where ean in ($1, $2)", EAN, EAN_ALTA)

    limpiar()
    sql(
        "insert into productos_canonicos (ean, nombre, marca, origen, calidad, estado_calidad, "
        "calidad_motivos, presentacion) values ($1, 'Desinfect Amb Origin', 'Lysoform', 'sepa', "
        "40, 'dudoso', '{abreviado,sin_tamano}', 'botella')",
        EAN,
    )
    yield
    limpiar()


def _usuario(client, rol: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {make_token()}"}
    uid = client.get("/v1/me", headers=h).json()["id"]
    if rol:
        hacer_rol(uid, rol)
    return {**h, "x-test-uid": uid}  # el último no lo lee el backend: es para los tests


def _uid(h: dict) -> str:
    return h["x-test-uid"]


@pytest.fixture
def moderador(client):
    return _usuario(client, "moderador")


@pytest.fixture
def admin(client):
    return _usuario(client, "admin")


def _sugerir(client, h, ean=EAN, **cuerpo):
    return client.post("/v1/catalogo/sugerencias", headers=h, json={"ean": ean, **cuerpo})


def _producto(ean=EAN) -> dict:
    return dict(_consulta("select * from productos_canonicos where ean = $1", ean)[0])


def _karma(h) -> int:
    return _consulta("select karma from usuarios where id = $1::uuid", _uid(h))[0]["karma"]


def test_capacidades_por_rol():
    for rol, sugiere in (("usuario", False), ("moderador", True), ("admin", True)):
        assert puede(SimpleNamespace(rol=rol), "catalogo.sugerir") is sugiere
    assert not puede(SimpleNamespace(rol="moderador"), "catalogo.sugerencias.resolver")
    assert puede(SimpleNamespace(rol="admin"), "catalogo.sugerencias.resolver")
    assert not puede(SimpleNamespace(rol="moderador"), "admin.acceder")  # el panel es del admin


def test_me_informa_el_rol(client, moderador, auth):
    assert client.get("/v1/me", headers=moderador).json()["rol"] == "moderador"
    assert client.get("/v1/me", headers=auth).json()["rol"] == "usuario"


def test_un_usuario_comun_no_puede_sugerir_ni_resolver(client, auth):
    assert _sugerir(client, auth, nombre="X Y").status_code == 403
    assert client.get("/v1/admin/sugerencias", headers=auth).status_code == 403


def test_un_moderador_no_entra_al_panel_ni_resuelve(client, moderador):
    assert client.get("/v1/admin/sugerencias", headers=moderador).status_code == 403
    assert client.get("/v1/admin/me", headers=moderador).status_code == 403


def test_un_moderador_restringido_por_karma_no_puede_sugerir(client, moderador):
    poner_karma(_uid(moderador), -20)
    r = _sugerir(client, moderador, nombre="Desinfectante Ambiental")
    assert r.status_code == 403
    assert r.json()["detail"]["codigo"] == "cuenta_restringida"


def test_sugerir_una_correccion_queda_pendiente_y_no_toca_el_catalogo(client, moderador):
    r = _sugerir(client, moderador, nombre="Desinfectante Ambiental", motivo="está abreviado")
    assert r.status_code == 201, r.text
    d = r.json()
    assert (d["tipo"], d["estado"], d["ean"]) == ("correccion", "pendiente", EAN)
    assert _producto()["nombre"] == "Desinfect Amb Origin"
    assert _producto()["campos_bloqueados"] == []
    mias = client.get("/v1/catalogo/sugerencias/mias", headers=moderador).json()
    assert [m["id"] for m in mias] == [d["id"]]


def test_sugerir_valida(client, moderador):
    assert _sugerir(client, moderador).status_code == 422  # nada que sugerir
    assert _sugerir(client, moderador, nombre="  ").status_code == 422
    assert _sugerir(client, moderador, tamano_valor="5").status_code == 422  # sin unidad
    assert _sugerir(client, moderador, ean="123").status_code == 422
    # lo que ya dice el catálogo no es una sugerencia
    r = _sugerir(client, moderador, marca="Lysoform")
    assert r.status_code == 422 and "ya es lo que dice" in r.json()["detail"]
    # un alta sin nombre
    assert _sugerir(client, moderador, ean=EAN_ALTA, marca="Fanta").status_code == 422


def test_una_sugerencia_nueva_reemplaza_a_la_pendiente(client, moderador):
    a = _sugerir(client, moderador, nombre="Desinfectante").json()
    b = _sugerir(client, moderador, nombre="Desinfectante Ambiental").json()
    estados = {
        m["id"]: m["estado"]
        for m in client.get("/v1/catalogo/sugerencias/mias", headers=moderador).json()
    }
    assert estados == {a["id"]: "reemplazada", b["id"]: "pendiente"}


def test_aprobar_una_correccion_la_aplica_la_bloquea_y_premia(client, moderador, admin):
    s = _sugerir(
        client,
        moderador,
        nombre="Desinfectante Ambiental Original",
        tamano_valor="380",
        tamano_unidad="ml",
        pack_cantidad=2,
        presentacion="Lata",
    ).json()
    cola = client.get("/v1/admin/sugerencias", headers=admin).json()
    mia = next(x for x in cola["items"] if x["id"] == s["id"])
    assert mia["actual"]["nombre"] == "Desinfect Amb Origin"  # «actual → sugerido»
    assert mia["usuario_alias"]

    r = client.post(f"/v1/admin/sugerencias/{s['id']}/aprobar", headers=admin, json={})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "aprobada" and r.json()["resuelto_por_alias"]
    p = _producto()
    assert p["nombre"] == "Desinfectante Ambiental Original"
    assert (float(p["tamano_valor"]), p["tamano_unidad"], p["pack_cantidad"]) == (380.0, "ml", 2)
    assert p["presentacion"] == "lata"
    assert set(p["campos_bloqueados"]) == {"nombre", "tamano", "presentacion"}
    assert (p["estado_calidad"], p["calidad_motivos"]) == ("completo", [])  # recalculada
    assert _karma(moderador) == 3  # config karma_sugerencia_aprobada
    # queda en el historial del producto y en su ficha
    ficha = client.get(f"/v1/admin/productos/{p['id']}", headers=admin).json()
    assert [x["estado"] for x in ficha["sugerencias"]] == ["aprobada"]
    assert any(
        h["accion"] == "sugerencia.aprobar"
        for h in client.get("/v1/admin/auditoria?entidad=sugerencia", headers=admin).json()["items"]
    )
    # no se resuelve dos veces
    assert client.post(f"/v1/admin/sugerencias/{s['id']}/aprobar", headers=admin).status_code == 409


def test_aprobar_un_alta_crea_el_producto_manual_y_bloqueado(client, moderador, admin):
    s = _sugerir(client, moderador, ean=EAN_ALTA, nombre="Fanta", presentacion="lata").json()
    assert s["tipo"] == "alta"
    assert client.post(f"/v1/admin/sugerencias/{s['id']}/aprobar", headers=admin).status_code == 200
    p = _producto(EAN_ALTA)
    assert (p["origen"], p["nombre"], p["presentacion"]) == ("manual", "Fanta", "lata")
    assert set(p["campos_bloqueados"]) == {"nombre", "presentacion"}
    # lo carga una persona: aunque sea una palabra sin marca ni tamaño, no se descarta
    assert p["estado_calidad"] != "descartado"
    assert client.get(f"/v1/productos/{EAN_ALTA}", headers=moderador).status_code == 200


def test_sugerir_sobre_un_descartado_es_una_correccion(client, moderador, admin):
    sql(
        "update productos_canonicos set nombre = 'Aceite', marca = null, estado_calidad = "
        "'descartado' where ean = $1",
        EAN,
    )
    assert client.get(f"/v1/productos/{EAN}", headers=moderador).status_code == 404  # no se ve
    s = _sugerir(client, moderador, nombre="Aceite Girasol", marca="Cocinero").json()
    assert s["tipo"] == "correccion"
    client.post(f"/v1/admin/sugerencias/{s['id']}/aprobar", headers=admin)
    assert client.get(f"/v1/productos/{EAN}", headers=moderador).status_code == 200


def test_rechazar_exige_nota_y_no_toca_nada(client, moderador, admin):
    s = _sugerir(client, moderador, nombre="Otro nombre").json()
    url = f"/v1/admin/sugerencias/{s['id']}/rechazar"
    assert client.post(url, headers=admin, json={}).status_code == 422
    r = client.post(url, headers=admin, json={"nota": "ese no es el nombre del envase"})
    assert r.status_code == 200 and r.json()["estado"] == "rechazada"
    assert r.json()["nota_resolucion"] == "ese no es el nombre del envase"
    assert _producto()["nombre"] == "Desinfect Amb Origin"
    assert _karma(moderador) == 0  # un rechazo no castiga por sí solo
    assert client.post(url, headers=admin, json={"nota": "otra vez"}).status_code == 409


def test_resolver_en_masa_informa_lo_que_fallo(client, moderador, admin):
    a = _sugerir(client, moderador, nombre="Desinfectante").json()
    b = _sugerir(client, moderador, ean=EAN_ALTA, nombre="Fanta").json()
    client.post(f"/v1/admin/sugerencias/{a['id']}/rechazar", headers=admin, json={"nota": "no va"})
    r = client.post(
        "/v1/admin/sugerencias/resolver",
        headers=admin,
        json={"ids": [a["id"], b["id"]], "accion": "aprobar"},
    ).json()
    assert r["resueltas"] == 1
    assert [f["id"] for f in r["fallidas"]] == [a["id"]]  # ya estaba resuelta
    assert _producto(EAN_ALTA)["nombre"] == "Fanta"
    sin_nota = client.post(
        "/v1/admin/sugerencias/resolver",
        headers=admin,
        json={"ids": [b["id"]], "accion": "rechazar"},
    )
    assert sin_nota.status_code == 422


def test_la_cola_filtra_por_estado_y_busca(client, moderador, admin):
    s = _sugerir(client, moderador, nombre="Desinfectante").json()
    pend = client.get("/v1/admin/sugerencias?q=7790000000055", headers=admin).json()
    assert [x["id"] for x in pend["items"]] == [s["id"]]
    assert (
        client.get("/v1/admin/sugerencias?estado=aprobada&q=7790000000055", headers=admin).json()[
            "total"
        ]
        == 0
    )
    assert client.get("/v1/admin/sugerencias?estado=otra", headers=admin).status_code == 422


def test_un_admin_cambia_el_rol_a_moderador(client, admin):
    u = _usuario(client)
    r = client.post(f"/v1/admin/usuarios/{_uid(u)}/rol", headers=admin, json={"rol": "moderador"})
    assert r.status_code == 200 and r.json()["rol"] == "moderador"
    assert client.get("/v1/me", headers=u).json()["rol"] == "moderador"
    assert client.get("/v1/admin/usuarios?rol=moderador", headers=admin).status_code == 200


# ----------------------------------------------------- alta y corrección directas (panel)


def test_alta_simple_del_panel(client, admin):
    r = client.post(
        "/v1/admin/productos",
        headers=admin,
        json={
            "ean": EAN_ALTA,
            "nombre": "Fanta",
            "marca": "Fanta",
            "presentacion": "Lata",
            "tamano_valor": None,
            "tamano_unidad": None,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["origen"] == "manual" and r.json()["estado_calidad"] != "descartado"
    p = _producto(EAN_ALTA)
    assert set(p["campos_bloqueados"]) == {"nombre", "marca", "presentacion"}
    # EAN que ya existe: 409; sin nombre: 422
    assert (
        client.post(
            "/v1/admin/productos", headers=admin, json={"ean": EAN, "nombre": "X Y"}
        ).status_code
        == 409
    )
    assert (
        client.post("/v1/admin/productos", headers=admin, json={"ean": "7790000000079"}).status_code
        == 422
    )


def test_buscar_por_ean_y_autocompletar_marca(client, admin):
    assert client.get(f"/v1/admin/productos/por-ean/{EAN_ALTA}", headers=admin).status_code == 404
    ficha = client.get(f"/v1/admin/productos/por-ean/{EAN}", headers=admin)
    assert ficha.status_code == 200 and ficha.json()["nombre"] == "Desinfect Amb Origin"
    assert "Lysoform" in client.get("/v1/admin/catalogo/marcas?q=lysof", headers=admin).json()
    assert client.get("/v1/admin/productos/por-ean/abc", headers=admin).status_code == 422


def test_corregir_la_presentacion_la_bloquea_contra_el_etl(client, admin):
    pid = str(_producto()["id"])
    r = client.patch(f"/v1/admin/productos/{pid}", headers=admin, json={"presentacion": "Lata"})
    assert r.status_code == 200 and r.json()["presentacion"] == "lata"
    assert "presentacion" in _producto()["campos_bloqueados"]
    # desbloquear la presentación también se puede
    r = client.post(
        f"/v1/admin/productos/{pid}/desbloquear", headers=admin, json={"campos": ["presentacion"]}
    )
    assert r.status_code == 200 and "presentacion" not in _producto()["campos_bloqueados"]


def test_un_pack_de_uno_no_es_un_pack(client, moderador, admin):
    """Regresión: el celular mandaba `pack_cantidad: 1` y la aprobación fallaba con un 500
    (la base exige pack > 1). Ahora «pack de 1» se guarda como «sin pack»."""
    s = _sugerir(client, moderador, nombre="Desinfectante Ambiental", pack_cantidad=1)
    assert s.status_code == 201 and "pack_cantidad" not in s.json()["cambios"]
    # una sugerencia vieja ya guardada con pack 1 también se aprueba
    sql(
        "update sugerencias_catalogo set cambios = cambios || '{\"pack_cantidad\": 1}' "
        "where id = $1::uuid",
        s.json()["id"],
    )
    r = client.post(f"/v1/admin/sugerencias/{s.json()['id']}/aprobar", headers=admin)
    assert r.status_code == 200, r.text
    assert _producto()["pack_cantidad"] is None
    pid = str(_producto()["id"])
    r = client.patch(f"/v1/admin/productos/{pid}", headers=admin, json={"pack_cantidad": 1})
    assert r.status_code == 200
