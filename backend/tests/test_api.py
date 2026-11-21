"""Smoke de endpoints contra Postgres real (requiere `make up`)."""

from tests.db import cuerpo_carga

EAN_SEED = "7790070411112"


def test_health(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "version" in r.json()


def test_requiere_token(client):
    assert client.get("/v1/me").status_code == 401
    assert client.get("/v1/me", headers={"Authorization": "Bearer basura"}).status_code == 401


def test_me_crea_usuario_con_karma_cero(client, auth):
    r = client.get("/v1/me", headers=auth)
    assert r.status_code == 200
    assert r.json()["karma"] == 0


def test_producto_inexistente_404(client, auth):
    assert client.get("/v1/productos/7799999999999", headers=auth).status_code == 404


def test_ean_balanza_rechazado(client, auth):
    assert client.get("/v1/productos/2000000012345", headers=auth).status_code == 422


def test_cargar_precio_suma_karma_y_aparece_en_historial(client, auth):
    local = client.get("/v1/locales", headers=auth).json()[0]
    r = client.post(
        "/v1/precios",
        headers=auth,
        json=cuerpo_carga(local["id"], EAN_SEED, "1234.50"),
    )
    assert r.status_code == 201
    assert r.json()["karma"] == 1

    hist = client.get(f"/v1/productos/{EAN_SEED}/precios", headers=auth).json()
    assert any(p["precio"] == "1234.50" for p in hist)
    assert client.get("/v1/me", headers=auth).json()["karma"] == 1


def test_precio_invalido_422(client, auth):
    local = client.get("/v1/locales", headers=auth).json()[0]
    r = client.post(
        "/v1/precios",
        headers=auth,
        json=cuerpo_carga(local["id"], EAN_SEED, "-1"),
    )
    assert r.status_code == 422
