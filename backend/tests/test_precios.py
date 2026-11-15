"""Carga de precios y karma, contra Postgres real."""

EAN_SEED = "7790070411112"


def _local_id(client, auth) -> str:
    return client.get("/v1/locales", headers=auth).json()[0]["id"]


def _cargar(client, auth, precio="100.00", ean=EAN_SEED, local_id=None):
    return client.post(
        "/v1/precios",
        headers=auth,
        json={
            "ean": ean,
            "local_id": local_id or _local_id(client, auth),
            "precio": precio,
        },
    )


def test_respuesta_trae_precio_id_y_karma(client, auth):
    r = _cargar(client, auth)
    assert r.status_code == 201
    assert set(r.json()) == {"precio_id", "karma"}
    # el id del precio no es el del usuario
    assert r.json()["precio_id"] != client.get("/v1/me", headers=auth).json()["id"]


def test_el_karma_se_acumula_por_carga(client, auth):
    assert _cargar(client, auth).json()["karma"] == 1
    assert _cargar(client, auth, "110").json()["karma"] == 2
    assert client.get("/v1/me", headers=auth).json()["karma"] == 2


def test_el_karma_es_por_usuario(client, auth):
    from tests.conftest import make_token

    otro = {"Authorization": f"Bearer {make_token()}"}
    _cargar(client, auth)
    assert client.get("/v1/me", headers=otro).json()["karma"] == 0


def test_precio_con_coma_o_ceros_se_guarda_exacto(client, auth):
    _cargar(client, auth, "1234.50")
    historial = client.get(f"/v1/productos/{EAN_SEED}/precios", headers=auth).json()
    assert "1234.50" in [p["precio"] for p in historial]


def test_una_carga_fallida_no_suma_karma(client, auth):
    antes = client.get("/v1/me", headers=auth).json()["karma"]
    assert _cargar(client, auth, ean="7799999999999").status_code == 404
    assert _cargar(client, auth, local_id="00000000-0000-0000-0000-00000000dead").status_code == 404
    assert _cargar(client, auth, precio="0").status_code == 422
    assert client.get("/v1/me", headers=auth).json()["karma"] == antes


def test_ean_de_balanza_no_se_puede_cargar(client, auth):
    assert _cargar(client, auth, ean="2000000012345").status_code == 422


def test_historial_trae_local_fecha_y_el_mas_nuevo_primero(client, auth):
    _cargar(client, auth, "100")
    _cargar(client, auth, "120.50")

    historial = client.get(f"/v1/productos/{EAN_SEED}/precios", headers=auth).json()

    assert [p["precio"] for p in historial][:2] == ["120.50", "100.00"]
    primero = historial[0]
    assert primero["local_nombre"] == "Local del admin"
    assert primero["fecha"].startswith("20")  # ISO 8601
    assert "T" in primero["fecha"]


def test_historial_de_un_producto_sin_precios_es_lista_vacia(client, auth):
    r = client.get("/v1/productos/7799999999999/precios", headers=auth)
    assert r.status_code == 200
    assert r.json() == []
