"""Cambio de alias: reglas, permiso por rol (config), tope diario e historial."""

import uuid

import pytest

from app.services import alias as svc
from tests.conftest import make_token
from tests.db import hacer_rol, poner_karma


def _nuevo(client, rol: str = "usuario"):
    h = {"Authorization": f"Bearer {make_token()}"}
    uid = client.get("/v1/me", headers=h).json()["id"]
    if rol != "usuario":
        hacer_rol(uid, rol)
    return h, uid


def _ficha(client, uid):
    h, _ = _nuevo(client, "admin")
    return client.get(f"/v1/admin/usuarios/{uid}", headers=h).json()["alias_historial"]


def _nombre(prefijo: str = "Ali") -> str:
    return f"{prefijo}{uuid.uuid4().hex[:8]}"


@pytest.fixture
def moderador(client):
    return _nuevo(client, "moderador")


# ------------------------------------------------------------- reglas puras


@pytest.mark.parametrize("alias", ["Juan", "juan_perez", "Ana-María", "ñandú 2", "a.b", "Pedro99"])
def test_formatos_validos(alias):
    assert svc.error_de_formato(alias) is None


@pytest.mark.parametrize(
    "alias",
    ["ab", "x" * 25, "-juan", "juan.", "ju  an", "ju..an", "a😀bc", "ju​an", "ju\nan", "   "],
)
def test_formatos_invalidos(alias):
    assert svc.error_de_formato(svc.normalizar(alias)) == "alias_invalido"


@pytest.mark.parametrize(
    "alias", ["anon-123456", "ANON-x", "admin", "Admin2", "A.d.m.i.n", "Moderador", "s0porte"]
)
def test_reservados(alias):
    assert svc.es_reservado(alias)


def test_no_reservados():
    assert not svc.es_reservado("Administradora de mi casa")  # no es la palabra sola
    assert not svc.es_reservado("juan")


def test_normalizar_recorta_y_compone_unicode():
    assert svc.normalizar("  José  ") == "José"


# ---------------------------------------------------------------- permisos


def test_usuario_comun_no_puede_con_el_default(client):
    h, _ = _nuevo(client)
    assert client.get("/v1/me", headers=h).json()["puede_cambiar_alias"] is False
    r = client.post("/v1/me/alias", headers=h, json={"alias": _nombre()})
    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "alias_no_permitido"


def test_moderador_cambia_y_el_me_lo_refleja(client, moderador):
    h, uid = moderador
    assert client.get("/v1/me", headers=h).json()["puede_cambiar_alias"] is True
    nuevo = _nombre()
    r = client.post("/v1/me/alias", headers=h, json={"alias": f"  {nuevo}  "})
    assert r.status_code == 200 and r.json() == {"alias": nuevo}
    assert client.get("/v1/me", headers=h).json()["alias"] == nuevo


def test_abrir_a_usuarios_con_el_interruptor(client, config_temporal):
    h, _ = _nuevo(client)
    config_temporal("alias_editable_por_rol", '["usuario", "moderador", "admin"]')
    assert client.get("/v1/me", headers=h).json()["puede_cambiar_alias"] is True
    assert client.post("/v1/me/alias", headers=h, json={"alias": _nombre()}).status_code == 200


def test_el_admin_siempre_puede_aunque_no_figure(client, config_temporal):
    h, uid = _nuevo(client, "admin")
    config_temporal("alias_editable_por_rol", "[]")
    assert client.post("/v1/me/alias", headers=h, json={"alias": _nombre()}).status_code == 200


def test_un_restringido_por_karma_no_puede(client, moderador):
    h, uid = moderador
    poner_karma(uid, -50)
    r = client.post("/v1/me/alias", headers=h, json={"alias": _nombre()})
    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "cuenta_restringida"


# --------------------------------------------------------------- validación


def test_invalido_y_reservado_dan_422_con_codigo(client, moderador):
    h, _ = moderador
    r = client.post("/v1/me/alias", headers=h, json={"alias": "a"})
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "alias_invalido"
    r = client.post("/v1/me/alias", headers=h, json={"alias": "anon-abcdef"})
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "alias_reservado"
    r = client.post("/v1/me/alias", headers=h, json={"alias": "Admin"})
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "alias_reservado"


def test_lista_de_bloqueados_de_config(client, moderador, config_temporal):
    h, _ = moderador
    config_temporal("alias_bloqueados", '["feo"]')
    r = client.post("/v1/me/alias", headers=h, json={"alias": "El F.é.o Juan"})
    assert r.status_code == 422 and r.json()["detail"]["codigo"] == "alias_bloqueado"


def test_unico_sin_distinguir_mayusculas_y_liberado_al_cambiar(client, config_temporal):
    config_temporal("alias_editable_por_rol", '["usuario", "moderador", "admin"]')
    ha, _ = _nuevo(client)
    hb, _ = _nuevo(client)
    nombre = _nombre("Uni")
    assert client.post("/v1/me/alias", headers=ha, json={"alias": nombre}).status_code == 200
    r = client.post("/v1/me/alias", headers=hb, json={"alias": nombre.upper()})
    assert r.status_code == 409 and r.json()["detail"]["codigo"] == "alias_en_uso"
    # El mismo usuario puede cambiar solo la capitalización de su alias.
    assert (
        client.post("/v1/me/alias", headers=ha, json={"alias": nombre.lower()}).status_code == 200
    )
    # Al cambiar, el alias anterior se libera.
    assert client.post("/v1/me/alias", headers=ha, json={"alias": _nombre()}).status_code == 200
    assert client.post("/v1/me/alias", headers=hb, json={"alias": nombre}).status_code == 200


def test_mismo_alias_no_cambia_nada_ni_gasta_cupo(client, moderador):
    h, uid = moderador
    nombre = _nombre()
    client.post("/v1/me/alias", headers=h, json={"alias": nombre})
    r = client.post("/v1/me/alias", headers=h, json={"alias": nombre})
    assert r.status_code == 200 and r.json() == {"alias": nombre}
    ficha = _ficha(client, uid)
    assert [x["alias_nuevo"] for x in ficha][:2] == [nombre, ficha[1]["alias_nuevo"]]
    assert len(ficha) == 2  # el alta y UN cambio


# ------------------------------------------------------------------- tope


def test_tope_diario_de_cambios(client, moderador, config_temporal):
    h, _ = moderador
    config_temporal("alias_max_cambios_por_dia", "2")
    for _ in range(2):
        assert client.post("/v1/me/alias", headers=h, json={"alias": _nombre()}).status_code == 200
    r = client.post("/v1/me/alias", headers=h, json={"alias": _nombre()})
    assert r.status_code == 429 and r.json()["detail"]["codigo"] == "limite_alias"


def test_el_admin_no_tiene_tope(client, config_temporal):
    h, _ = _nuevo(client, "admin")
    config_temporal("alias_max_cambios_por_dia", "1")
    for _ in range(3):
        assert client.post("/v1/me/alias", headers=h, json={"alias": _nombre()}).status_code == 200


# --------------------------------------------------------------- historial


def test_el_historial_guarda_anterior_nuevo_autor_y_origen(client, moderador):
    h, uid = moderador
    admin_h, admin_id = _nuevo(client, "admin")
    original = client.get("/v1/me", headers=h).json()["alias"]
    primero, segundo = _nombre(), _nombre()
    client.post("/v1/me/alias", headers=h, json={"alias": primero})
    r = client.patch(f"/v1/admin/usuarios/{uid}", headers=admin_h, json={"alias": segundo})
    assert r.status_code == 200
    ficha = client.get(f"/v1/admin/usuarios/{uid}", headers=admin_h).json()
    hist = ficha["alias_historial"]
    assert [x["alias_nuevo"] for x in hist] == [segundo, primero, original]  # más nuevo primero
    assert hist[0]["alias_anterior"] == primero and hist[0]["origen"] == "admin"
    assert hist[0]["cambiado_por_id"] == admin_id
    assert hist[1]["origen"] == "usuario" and hist[1]["cambiado_por_id"] == uid
    assert hist[2]["origen"] == "alta" and hist[2]["alias_anterior"] is None
    assert hist[0]["cambiado_en"].endswith("Z") or "+00:00" in hist[0]["cambiado_en"]


def test_admin_sin_permiso_no_ve_historial_ajeno(client, moderador):
    h, uid = moderador
    assert client.get(f"/v1/admin/usuarios/{uid}", headers=h).status_code == 403
