"""Reclamar una cuenta huérfana para una cuenta ligada (panel, corte 21).

Diseño: docs/superpowers/specs/2026-11-26-cuentas-ligables-design.md («Huérfanas y reclamo»).
"""

import random
import uuid

import pytest

from app.services import dispositivos
from tests.conftest import make_token
from tests.db import fila, hacer_admin, poner_estado, poner_karma, sql

EAN = "7790000000555"  # lo usa solo este módulo


@pytest.fixture(autouse=True)
def _producto_y_limpieza():
    sql(
        "insert into productos_canonicos (ean, nombre, origen) values ($1, 'Reclamos', 'manual') "
        "on conflict do nothing",
        EAN,
    )
    yield
    de_los_locales = "(select id from locales where nombre like 'rec-%')"
    sql(
        "delete from validaciones where precio_id in "
        f"(select id from precios where local_id in {de_los_locales})"
    )
    sql(f"delete from precios where local_id in {de_los_locales}")
    sql("delete from locales where nombre like 'rec-%'")


def _cuenta(client, ligada=False, karma=0, rol=None):
    """(headers, usuarios.id, auth_id). `ligada` la deja con email y sin es_anonimo."""
    auth_id = str(uuid.uuid4())
    h = {"Authorization": f"Bearer {make_token(auth_id)}"}
    uid = client.get("/v1/me", headers=h).json()["id"]
    if ligada:
        sql(
            "update usuarios set es_anonimo = false, email = $2 where id = $1::uuid",
            uid,
            f"{auth_id}@example.com",
        )
    if karma:
        poner_karma(uid, karma)
    if rol == "admin":
        hacer_admin(uid)
    return h, uid, auth_id


@pytest.fixture
def admin(client):
    h, uid, _ = _cuenta(client, rol="admin")
    return h, uid


def _local(client, adm) -> str:
    r = client.post(
        "/v1/locales",
        headers=adm,
        json={
            "nombre": f"rec-{uuid.uuid4().hex[:8]}",
            "lat": random.uniform(-60, -50),
            "lng": random.uniform(-40, -30),
        },
    )
    return r.json()["id"]


def _precio(uid: str, local: str, precio: str = "100") -> str:
    """Precio cargado directamente por `uid` (atribución para probar el reclamo)."""
    sql(
        "insert into precios (producto_canonico_id, local_id, precio, user_id) "
        "select (select id from productos_canonicos where ean = $1), $2::uuid, $3::numeric, "
        "$4::uuid",
        EAN,
        local,
        precio,
        uid,
    )
    return fila("select id from precios where user_id = $1::uuid order by created_at desc", uid)[
        "id"
    ]


def _reclamar(client, adm, destino: str, huerfana: str, motivo="es la misma persona"):
    return client.post(
        f"/v1/admin/usuarios/{destino}/reclamar",
        headers=adm,
        json={"huerfana_id": huerfana, "motivo": motivo},
    )


def test_reclamo_pasa_karma_y_cargas_y_deja_a_la_huerfana_fusionada(client, admin):
    ha, aid = admin
    local = _local(client, ha)
    _, destino, _ = _cuenta(client, ligada=True, karma=4)
    _, huerfana, _ = _cuenta(client, karma=7)
    alias_destino = fila("select alias from usuarios where id = $1::uuid", destino)["alias"]
    pid = _precio(huerfana, local)

    r = _reclamar(client, ha, destino, huerfana)

    assert r.status_code == 200 and r.json() == {"filas_sin_pasar": 0}
    d = fila("select karma, alias from usuarios where id = $1::uuid", destino)
    assert d["karma"] == 4 + 7 and d["alias"] == alias_destino
    h = fila(
        "select estado, fusionada_en, karma, baja_at from usuarios where id = $1::uuid", huerfana
    )
    assert h["estado"] == "fusionada" and str(h["fusionada_en"]) == destino
    assert h["karma"] == 0 and h["baja_at"] is None
    ficha = client.get(f"/v1/admin/usuarios/{huerfana}", headers=ha).json()
    assert ficha["estado"] == "fusionada" and ficha["fusionada_en"] == destino
    assert str(fila("select user_id from precios where id = $1", pid)["user_id"]) == destino
    a = fila(
        "select usuario_id, nota from auditoria_admin where accion = 'usuario.reclamar' "
        "and entidad_id = $1",
        destino,
    )
    assert str(a["usuario_id"]) == aid and a["nota"] == "es la misma persona"


def test_la_huerfana_fusionada_ya_no_entra(client, admin):
    ha, _ = admin
    h_huerfana, huerfana, _ = _cuenta(client)
    _, destino, _ = _cuenta(client, ligada=True)
    assert _reclamar(client, ha, destino, huerfana).status_code == 200

    r = client.get("/v1/me", headers=h_huerfana)

    assert r.status_code == 403 and r.json()["detail"]["codigo"] == "cuenta_fusionada"


def test_el_karma_negativo_de_la_huerfana_resta(client, admin):
    ha, _ = admin
    _, destino, _ = _cuenta(client, ligada=True, karma=10)
    _, huerfana, _ = _cuenta(client, karma=-4)
    assert _reclamar(client, ha, destino, huerfana).status_code == 200
    assert fila("select karma from usuarios where id = $1::uuid", destino)["karma"] == 6


def test_el_motivo_es_obligatorio(client, admin):
    ha, _ = admin
    _, destino, _ = _cuenta(client, ligada=True)
    _, huerfana, _ = _cuenta(client)
    assert _reclamar(client, ha, destino, huerfana, motivo="ab").status_code == 422
    assert _reclamar(client, ha, destino, huerfana, motivo="x" * 301).status_code == 422


def test_no_se_reclama_a_si_misma(client, admin):
    ha, _ = admin
    _, uid, _ = _cuenta(client, ligada=True)
    assert _reclamar(client, ha, uid, uid).status_code == 422


@pytest.mark.parametrize(
    "caso",
    ["huerfana_ya_fusionada", "destino_anonimo", "destino_de_baja", "huerfana_ligada",
     "huerfana_de_baja"],
)  # fmt: skip
def test_reclamos_invalidos_409_sin_tocar_nada(client, admin, caso):
    ha, _ = admin
    _, destino, _ = _cuenta(client, ligada=caso != "destino_anonimo", karma=3)
    _, huerfana, _ = _cuenta(client, ligada=caso == "huerfana_ligada", karma=5)
    if caso == "huerfana_ya_fusionada":
        _, otro, _ = _cuenta(client, ligada=True)
        poner_estado(huerfana, "fusionada", otro)
    if caso == "destino_de_baja":
        poner_estado(destino, "baja")
    if caso == "huerfana_de_baja":
        poner_estado(huerfana, "baja")

    r = _reclamar(client, ha, destino, huerfana)

    assert r.status_code == 409
    assert fila("select karma from usuarios where id = $1::uuid", destino)["karma"] == 3
    assert fila("select karma from usuarios where id = $1::uuid", huerfana)["karma"] == 5


def test_reclamar_dos_veces_la_misma_huerfana_409(client, admin):
    ha, _ = admin
    _, destino, _ = _cuenta(client, ligada=True)
    _, huerfana, _ = _cuenta(client, karma=2)
    assert _reclamar(client, ha, destino, huerfana).status_code == 200
    assert _reclamar(client, ha, destino, huerfana).status_code == 409
    assert fila("select karma from usuarios where id = $1::uuid", destino)["karma"] == 2


def test_un_conflicto_de_unicidad_deja_la_fila_con_la_huerfana_y_se_avisa(client, admin):
    ha, _ = admin
    local = _local(client, ha)
    _, destino, _ = _cuenta(client, ligada=True)
    _, huerfana, _ = _cuenta(client)
    pid = _precio(destino, local)
    for uid in (destino, huerfana):  # los dos validaron el MISMO precio: (precio_id, user_id)
        sql(
            "insert into validaciones (precio_id, user_id, resultado) values ($1, $2::uuid, 'ok')",
            pid,
            uid,
        )

    r = _reclamar(client, ha, destino, huerfana)

    assert r.status_code == 200 and r.json() == {"filas_sin_pasar": 1}
    q = "select count(*) as n from validaciones where user_id = $1::uuid"
    assert fila(q, destino)["n"] == 1 and fila(q, huerfana)["n"] == 1


def test_un_usuario_comun_no_puede_reclamar(client):
    h, _, _ = _cuenta(client, ligada=True)
    _, destino, _ = _cuenta(client, ligada=True)
    _, huerfana, _ = _cuenta(client)
    assert _reclamar(client, h, destino, huerfana).status_code == 403


def test_la_ficha_muestra_si_esta_ligada_y_las_cuentas_del_mismo_dispositivo(client, admin):
    ha, _ = admin
    _, destino, destino_auth = _cuenta(client, ligada=True)
    _, huerfana, huerfana_auth = _cuenta(client)
    device = dispositivos.hashear(f"dev-{uuid.uuid4().hex}")
    for auth in (destino_auth, huerfana_auth):
        sql("insert into dispositivos (hash, auth_id) values ($1, $2::uuid)", device, auth)

    ficha = client.get(f"/v1/admin/usuarios/{destino}", headers=ha).json()

    assert ficha["es_anonimo"] is False and ficha["email"] == f"{destino_auth}@example.com"
    hermana = next(c for c in ficha["mismo_dispositivo"] if c["id"] == huerfana)
    assert hermana["es_anonimo"] is True and hermana["estado"] == "activo"
