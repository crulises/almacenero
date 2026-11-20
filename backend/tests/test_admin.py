"""/v1/admin: permisos, login, usuarios, locales, precios, config, catálogo y auditoría,
contra Postgres real. El proveedor de auth (GoTrue) se simula solo en el login."""

import asyncio
import uuid

import asyncpg
import httpx
import pytest

from app.config import get_settings
from app.main import app
from tests.conftest import make_token
from tests.db import cuerpo_carga, hacer_admin, sql

EAN = "7790070411112"  # del seed
LOCAL_SEED = "00000000-0000-0000-0000-000000000001"


def _consulta(query: str, *args):
    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            return await conn.fetch(query, *args)
        finally:
            await conn.close()

    return asyncio.run(run())


@pytest.fixture(autouse=True, scope="module")
def _limpiar():
    yield
    sql("delete from precios where local_id in (select id from locales where nombre like 'adm-%')")
    sql("delete from precios where precio in (7777.77, 8888.88)")
    sql("delete from locales where nombre like 'adm-%'")
    sql("delete from usuarios where email like 'adm-%@test.com'")
    sql("delete from conflictos_catalogo where ean = '7790000000017'")
    sql("delete from productos_canonicos where ean = '7790000000017'")


@pytest.fixture
def admin(client):
    h = {"Authorization": f"Bearer {make_token()}"}
    hacer_admin(client.get("/v1/me", headers=h).json()["id"])
    return h


def _mi_id(client, headers) -> str:
    return client.get("/v1/me", headers=headers).json()["id"]


def _local(nombre=None, verificado=False, fuente="manual") -> str:
    lid = str(uuid.uuid4())
    sql(
        """
        insert into locales (id, nombre, ubicacion, verificado, fuente)
        values ($1::uuid, $2, st_setsrid(st_makepoint(-35.0, -55.0), 4326)::geography, $3, $4)
        """,
        lid,
        nombre or f"adm-{uuid.uuid4().hex[:8]}",
        verificado,
        fuente,
    )
    return lid


# ------------------------------------------------------------------ permisos
@pytest.mark.parametrize(
    "ruta",
    ["/usuarios", "/locales", "/precios", "/config", "/productos", "/conflictos", "/auditoria"],
)
def test_un_usuario_comun_no_entra(client, auth, ruta):
    assert client.get(f"/v1/admin{ruta}", headers=auth).status_code == 403


def test_sin_token_401(client):
    assert client.get("/v1/admin/usuarios").status_code == 401


def test_acciones_de_un_usuario_comun_403(client, auth):
    assert (
        client.post(
            "/v1/admin/locales/validar", headers=auth, json={"ids": [LOCAL_SEED]}
        ).status_code
        == 403
    )
    assert (
        client.put("/v1/admin/config/geofence_metros", headers=auth, json={"valor": 1}).status_code
        == 403
    )


def test_admin_me(client, admin):
    r = client.get("/v1/admin/me", headers=admin)
    assert r.status_code == 200
    assert r.json()["rol"] == "admin"


# --------------------------------------------------------------------- login
@pytest.fixture
def gotrue(client, monkeypatch):
    """GoTrue simulado: devuelve un JWT real firmado con el secreto del backend."""
    s = get_settings()
    monkeypatch.setattr(s, "auth_url", "http://auth.test/auth/v1")
    monkeypatch.setattr(s, "auth_api_key", "clave-publica")
    estado = {"token": make_token(), "status": 200, "visto": None}

    def handler(req: httpx.Request) -> httpx.Response:
        estado["visto"] = req
        if estado["status"] != 200:
            return httpx.Response(estado["status"], json={})
        return httpx.Response(
            200,
            json={"access_token": estado["token"], "refresh_token": "r", "expires_in": 3600},
        )

    original = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    yield estado
    app.state.http = original


def test_login_de_admin(client, gotrue):
    hacer_admin(
        client.get("/v1/me", headers={"Authorization": f"Bearer {gotrue['token']}"}).json()["id"]
    )
    r = client.post("/v1/admin/login", json={"email": "a@b.com", "password": "x"})
    assert r.status_code == 200
    assert r.json()["usuario"]["rol"] == "admin"
    assert r.json()["access_token"] == gotrue["token"]
    assert gotrue["visto"].url.query == b"grant_type=password"


def test_login_de_un_no_admin_403_y_sin_sesion(client, gotrue):
    r = client.post("/v1/admin/login", json={"email": "a@b.com", "password": "x"})
    assert r.status_code == 403
    assert "access_token" not in r.text


def test_login_con_credenciales_malas_401(client, gotrue):
    gotrue["status"] = 400
    assert (
        client.post("/v1/admin/login", json={"email": "a@b.com", "password": "x"}).status_code
        == 401
    )


# ------------------------------------------------------------------ usuarios
def test_usuarios_anonimos_y_registrados(client, admin):
    # Un registrado: el JWT trae email e is_anonymous=false.
    import time

    import jwt

    s = get_settings()
    mail1 = f"adm-{uuid.uuid4().hex[:8]}@test.com"
    mail2 = f"adm-{uuid.uuid4().hex[:8]}@test.com"
    sub = str(uuid.uuid4())
    ahora = int(time.time())
    token = jwt.encode(
        {
            "sub": sub,
            "aud": s.jwt_audience,
            "iat": ahora,
            "exp": ahora + 3600,
            "email": mail1,
            "is_anonymous": False,
        },
        s.jwt_secret,
        algorithm="HS256",
    )
    client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})

    r = client.get(f"/v1/admin/usuarios?tipo=registrado&q={mail1}", headers=admin)
    assert r.status_code == 200
    u = r.json()["items"][0]
    assert u["email"] == mail1 and u["es_anonimo"] is False
    assert u["anonimo_auth_id"] is None  # nació registrado: sin anónimo asociado

    # Un anónimo que luego se registra conserva la asociación con su id anónimo.
    sub2 = str(uuid.uuid4())
    anon = {"Authorization": f"Bearer {make_token(sub2)}"}
    client.get("/v1/me", headers=anon)
    ligado = jwt.encode(
        {
            "sub": sub2,
            "aud": s.jwt_audience,
            "iat": ahora,
            "exp": ahora + 3600,
            "email": mail2,
            "is_anonymous": False,
        },
        s.jwt_secret,
        algorithm="HS256",
    )
    client.get("/v1/me", headers={"Authorization": f"Bearer {ligado}"})
    u2 = client.get(f"/v1/admin/usuarios?q={mail2}", headers=admin).json()["items"][0]
    assert u2["es_anonimo"] is False
    assert u2["anonimo_auth_id"] == sub2

    anonimos = client.get("/v1/admin/usuarios?tipo=anonimo&limit=5", headers=admin).json()
    assert anonimos["total"] >= 1
    assert all(x["es_anonimo"] for x in anonimos["items"])


def test_usuarios_muestra_cargas_y_se_edita_el_alias(client, admin):
    uid = _mi_id(client, admin)
    u = client.get(f"/v1/admin/usuarios?q={uid}", headers=admin).json()["items"][0]
    assert u["id"] == uid and u["cargas"] == 0
    r = client.patch(f"/v1/admin/usuarios/{uid}", headers=admin, json={"alias": "adm-alias"})
    assert r.status_code == 200 and r.json()["alias"] == "adm-alias"
    assert (
        client.patch(f"/v1/admin/usuarios/{uid}", headers=admin, json={"alias": "  "}).status_code
        == 422
    )
    log = client.get(f"/v1/admin/auditoria?entidad=usuario&entidad_id={uid}", headers=admin).json()
    assert log["items"][0]["despues"] == {"alias": "adm-alias"}


def test_el_rol_no_se_cambia_por_la_api(client, admin):
    uid = _mi_id(client, admin)
    r = client.patch(
        f"/v1/admin/usuarios/{uid}", headers=admin, json={"alias": "x", "rol": "usuario"}
    )
    assert r.status_code == 200
    assert client.get("/v1/admin/me", headers=admin).json()["rol"] == "admin"


# ------------------------------------------------------------------- locales
def test_filtrar_validar_en_masa_y_auditar(client, admin):
    a, b = _local(fuente="osm"), _local(fuente="sepa")
    r = client.get("/v1/admin/locales?verificado=false&fuente=osm&q=adm-", headers=admin)
    assert a in [x["id"] for x in r.json()["items"]]
    assert b not in [x["id"] for x in r.json()["items"]]

    r = client.post("/v1/admin/locales/validar", headers=admin, json={"ids": [a, b, LOCAL_SEED]})
    assert r.status_code == 200
    assert r.json()["afectados"] == 2  # el del seed ya estaba verificado
    assert r.json()["omitidos"] == [LOCAL_SEED]
    ver = client.get("/v1/admin/locales?verificado=true&q=adm-", headers=admin).json()["items"]
    assert {a, b} <= {x["id"] for x in ver}
    log = client.get(f"/v1/admin/auditoria?entidad=local&entidad_id={a}", headers=admin).json()
    assert log["items"][0]["accion"] == "local.validar"


def test_corregir_local(client, admin):
    lid = _local()
    nuevo = f"adm-corregido-{uuid.uuid4().hex[:6]}"
    r = client.patch(
        f"/v1/admin/locales/{lid}",
        headers=admin,
        json={"nombre": nuevo, "direccion": "Calle 9", "lat": -34.5, "lng": -58.4},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["nombre"] == nuevo and d["lat"] == pytest.approx(-34.5)
    assert d["lng"] == pytest.approx(-58.4)
    log = client.get(f"/v1/admin/auditoria?entidad=local&entidad_id={lid}", headers=admin).json()
    assert log["items"][0]["antes"]["nombre"].startswith("adm-")
    assert log["items"][0]["despues"]["nombre"] == nuevo
    # validaciones de entrada
    assert (
        client.patch(f"/v1/admin/locales/{lid}", headers=admin, json={"lat": 1}).status_code == 422
    )
    assert (
        client.patch(f"/v1/admin/locales/{lid}", headers=admin, json={"nombre": " "}).status_code
        == 422
    )
    assert client.patch(f"/v1/admin/locales/{lid}", headers=admin, json={}).status_code == 422
    assert (
        client.patch(
            f"/v1/admin/locales/{uuid.uuid4()}", headers=admin, json={"nombre": "x"}
        ).status_code
        == 404
    )


def test_fusionar_locales_mueve_los_precios(client, admin, auth):
    destino, origen = _local(), _local()
    uid = _mi_id(client, auth)
    sql(
        "insert into precios (producto_canonico_id, local_id, precio, user_id) "
        "select id, $1::uuid, 7777.77, $2::uuid from productos_canonicos where ean = $3",
        origen,
        uid,
        EAN,
    )
    sql(
        "insert into local_fuentes (local_id, fuente, ref) values ($1::uuid, 'osm', $2)",
        origen,
        f"node/{uuid.uuid4().hex}",
    )
    r = client.post(
        "/v1/admin/locales/fusionar",
        headers=admin,
        json={"destino_id": destino, "origen_ids": [origen]},
    )
    assert r.status_code == 200
    assert r.json()["precios"] == 1 and len(r.json()["refs"]) == 1
    assert _consulta("select 1 from locales where id = $1::uuid", origen) == []
    assert (
        client.post(
            "/v1/admin/locales/fusionar",
            headers=admin,
            json={"destino_id": destino, "origen_ids": [destino]},
        ).status_code
        == 422
    )


def test_borrar_locales_omite_los_que_tienen_precios(client, admin, auth):
    vacio, con_precio = _local(), _local()
    sql(
        "insert into precios (producto_canonico_id, local_id, precio, user_id) "
        "select id, $1::uuid, 7777.77, $2::uuid from productos_canonicos where ean = $3",
        con_precio,
        _mi_id(client, auth),
        EAN,
    )
    r = client.post("/v1/admin/locales/borrar", headers=admin, json={"ids": [vacio, con_precio]})
    assert r.json()["afectados"] == 1 and r.json()["omitidos"] == [con_precio]
    assert _consulta("select 1 from locales where id = $1::uuid", vacio) == []
    log = client.get(f"/v1/admin/auditoria?entidad=local&entidad_id={vacio}", headers=admin).json()
    assert log["items"][0]["accion"] == "local.borrar"


# -------------------------------------------------------------------- precios
def _cargar(client, auth, local_id, precio="8888.88"):
    r = client.post("/v1/precios", headers=auth, json=cuerpo_carga(local_id, EAN, precio))
    assert r.status_code == 201, r.text
    return r.json()["precio_id"]


def test_listar_corregir_y_borrar_precios_con_rastro(client, admin, auth):
    lid = _local()
    pid = _cargar(client, auth, lid)
    uid = _mi_id(client, auth)

    r = client.get(f"/v1/admin/precios?local_id={lid}&ean={EAN}&user_id={uid}", headers=admin)
    assert [p["id"] for p in r.json()["items"]] == [pid]
    assert r.json()["items"][0]["local_nombre"].startswith("adm-")

    r = client.patch(f"/v1/admin/precios/{pid}", headers=admin, json={"precio": "7777.77"})
    assert r.status_code == 200 and r.json()["precio"] == "7777.77"
    assert (
        client.patch(f"/v1/admin/precios/{pid}", headers=admin, json={"precio": "0"}).status_code
        == 422
    )

    assert client.delete(f"/v1/admin/precios/{pid}", headers=admin).status_code == 204
    assert client.delete(f"/v1/admin/precios/{pid}", headers=admin).status_code == 404
    log = client.get(f"/v1/admin/auditoria?entidad=precio&entidad_id={pid}", headers=admin).json()
    assert [x["accion"] for x in log["items"]] == ["precio.borrar", "precio.corregir"]
    assert log["items"][0]["antes"]["precio"] == "7777.77"  # el rastro guarda la fila


def test_borrar_precios_en_masa(client, admin, auth):
    lid = _local()
    ids = [_cargar(client, auth, lid) for _ in range(2)]
    r = client.post(
        "/v1/admin/precios/borrar", headers=admin, json={"ids": [*ids, str(uuid.uuid4())]}
    )
    assert r.json()["afectados"] == 2 and len(r.json()["omitidos"]) == 1


# --------------------------------------------------------------------- config
def test_config_listar_y_cambiar(client, admin):
    items = client.get("/v1/admin/config", headers=admin).json()
    assert "geofence_metros" in [i["clave"] for i in items]
    previo = next(i["valor"] for i in items if i["clave"] == "geofence_metros")
    try:
        r = client.put("/v1/admin/config/geofence_metros", headers=admin, json={"valor": 222})
        assert r.status_code == 200 and r.json()["valor"] == 222
        assert client.get("/v1/config").json() is not None
        # el backend lee el valor nuevo
        assert any(
            c["clave"] == "geofence_metros" and c["valor"] == 222
            for c in client.get("/v1/config").json()
        )
    finally:
        client.put("/v1/admin/config/geofence_metros", headers=admin, json={"valor": previo})


def test_config_validaciones(client, admin):
    put = lambda k, v: client.put(f"/v1/admin/config/{k}", headers=admin, json={"valor": v})  # noqa: E731
    assert put("clave_que_no_existe", 1).status_code == 404
    assert put("geofence_metros", "mucho").status_code == 422
    assert put("geofence_metros", -5).status_code == 422
    assert put("alta_locales_abierta", 1).status_code == 422  # bool vs número


# ------------------------------------------------------------------- catálogo
def _producto() -> str:
    sql("delete from conflictos_catalogo where ean = '7790000000017'")
    sql("delete from productos_canonicos where ean = '7790000000017'")
    sql(
        "insert into productos_canonicos (ean, nombre, marca, tamano_valor, tamano_unidad, origen) "
        "values ('7790000000017', 'Adm Prod', 'Marca A', 500, 'g', 'off')"
    )
    return _consulta("select id from productos_canonicos where ean = '7790000000017'")[0]["id"]


def test_corregir_producto_bloquea_el_campo(client, admin):
    pid = str(_producto())
    r = client.patch(
        f"/v1/admin/productos/{pid}",
        headers=admin,
        json={"nombre": "Adm Corregido", "tamano_valor": "1", "tamano_unidad": "kg"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["nombre"] == "Adm Corregido" and d["tamano_unidad"] == "kg"
    assert set(d["campos_bloqueados"]) == {"nombre", "tamano"}
    # el trigger sigue protegiendo contra el ETL
    with pytest.raises(asyncpg.PostgresError):
        sql("update productos_canonicos set nombre = 'pisado' where ean = '7790000000017'")
    assert (
        client.patch(
            f"/v1/admin/productos/{pid}", headers=admin, json={"tamano_valor": 3}
        ).status_code
        == 422
    )
    assert client.get("/v1/admin/productos?q=7790000000017", headers=admin).json()["total"] == 1


def test_resolver_conflicto(client, admin):
    _producto()
    sql(
        "insert into conflictos_catalogo (ean, campo, valor_a, fuente_a, valor_b, fuente_b) "
        "values ('7790000000017', 'tamano', '500 g', 'off', '750 g', 'sepa')"
    )
    pend = client.get("/v1/admin/conflictos?ean=7790000000017", headers=admin).json()["items"]
    c = next(x for x in pend if x["ean"] == "7790000000017")
    r = client.post(
        f"/v1/admin/conflictos/{c['id']}/resolver", headers=admin, json={"elegido": "b"}
    )
    assert r.status_code == 200 and r.json()["estado"] == "resuelto"
    fila = _consulta(
        "select tamano_valor, tamano_unidad, campos_bloqueados "
        "from productos_canonicos where ean = '7790000000017'"
    )[0]
    assert (float(fila["tamano_valor"]), fila["tamano_unidad"]) == (750.0, "g")
    assert "tamano" in fila["campos_bloqueados"]
    assert (
        client.post(
            f"/v1/admin/conflictos/{c['id']}/resolver", headers=admin, json={"elegido": "a"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/v1/admin/conflictos/{c['id']}/resolver", headers=admin, json={"elegido": "z"}
        ).status_code
        == 422
    )


# ------------------------------------------------------------------ auditoría
def test_la_auditoria_no_se_modifica_ni_se_borra(client, admin):
    uid = _mi_id(client, admin)
    client.patch(f"/v1/admin/usuarios/{uid}", headers=admin, json={"alias": "adm-auditoria"})
    with pytest.raises(asyncpg.PostgresError):
        sql("update auditoria_admin set nota = 'x'")
    with pytest.raises(asyncpg.PostgresError):
        sql("delete from auditoria_admin")


# ----------------------------------------------------------------------- CORS
def test_cors_permite_al_panel_y_no_a_otros(client):
    ok = client.options(
        "/v1/admin/login",
        headers={"Origin": "http://localhost:8080", "Access-Control-Request-Method": "POST"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:8080"
    mal = client.options(
        "/v1/admin/login",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in mal.headers


# ============================================================ fichas por entidad
def _registrado(client) -> tuple[str, dict]:
    """Un usuario registrado (JWT con email e is_anonymous=false). Devuelve (id, headers)."""
    import time

    import jwt

    s = get_settings()
    ahora = int(time.time())
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": s.jwt_audience,
            "iat": ahora,
            "exp": ahora + 3600,
            "email": f"adm-{uuid.uuid4().hex[:8]}@test.com",
            "is_anonymous": False,
        },
        s.jwt_secret,
        algorithm="HS256",
    )
    h = {"Authorization": f"Bearer {token}"}
    return client.get("/v1/me", headers=h).json()["id"], h


@pytest.mark.parametrize("ruta", ["locales", "precios", "usuarios", "productos"])
def test_fichas_exigen_admin_y_dan_404(client, auth, admin, ruta):
    falso = uuid.uuid4()
    assert client.get(f"/v1/admin/{ruta}/{falso}", headers=auth).status_code == 403
    assert client.get(f"/v1/admin/{ruta}/{falso}", headers=admin).status_code == 404


def test_ficha_de_local_trae_el_contexto(client, admin, auth):
    lid = _local(fuente="osm", nombre="adm-Super Vecino")
    vecino = _local(nombre="adm-Super Vecinos")  # mismo punto, nombre parecido
    lejano = _local(nombre="adm-Zzzz Otro")  # mismo punto, nombre distinto
    _cargar(client, auth, lid)
    sql(
        "insert into local_fuentes (local_id, fuente, ref, datos) "
        "values ($1::uuid, 'osm', $2, '{\"brand\": \"X\"}'::jsonb)",
        lid,
        f"node/{uuid.uuid4().hex}",
    )
    client.patch(f"/v1/admin/locales/{lid}", headers=admin, json={"direccion": "Calle 5"})

    f = client.get(f"/v1/admin/locales/{lid}", headers=admin).json()
    assert f["fuente"] == "osm" and f["verificado"] is False and f["precios"] == 1
    assert f["fuentes"][0]["datos"] == {"brand": "X"}
    assert len(f["precios_recientes"]) == 1 and f["precios_recientes"][0]["ean"] == EAN
    ids = [d["id"] for d in f["duplicados"]]
    assert vecino in ids and lejano not in ids  # la similitud filtra
    assert f["duplicados"][0]["distancia_m"] < 1
    assert f["historial"][0]["accion"] == "local.corregir"


def test_corregir_un_local_hacia_un_duplicado_da_409_salvo_forzar(client, admin):
    _local(nombre="adm-Kiosco Central")
    otro = _local(nombre="adm-Almacen Sur")
    r = client.patch(
        f"/v1/admin/locales/{otro}", headers=admin, json={"nombre": "adm-Kiosco Central"}
    )
    assert r.status_code == 409
    assert r.json()["detail"]["codigo"] == "local_duplicado"
    ok = client.patch(
        f"/v1/admin/locales/{otro}",
        headers=admin,
        json={"nombre": "adm-Kiosco Central", "forzar": True},
    )
    assert ok.status_code == 200
    # el flag no es una columna ni queda en el rastro
    log = client.get(f"/v1/admin/auditoria?entidad=local&entidad_id={otro}", headers=admin).json()
    assert "forzar" not in (log["items"][0]["despues"] or {})


def test_ficha_de_precio_compara_con_el_resto_del_local(client, admin, auth):
    lid = _local()
    for monto in ("100", "100"):
        _cargar(client, auth, lid, monto)
    pid = _cargar(client, auth, lid, "150")
    f = client.get(f"/v1/admin/precios/{pid}", headers=admin).json()
    assert len(f["otros_en_el_local"]) == 2
    assert f["promedio_otros_local"] == "100.00"
    assert f["diferencia_pct"] == 50.0
    assert f["local_verificado"] is False and f["user_karma"] >= 3
    r = client.patch(
        f"/v1/admin/precios/{pid}", headers=admin, json={"precio": "101", "motivo": "tipeo"}
    )
    assert r.status_code == 200
    h = client.get(f"/v1/admin/precios/{pid}", headers=admin).json()["historial"]
    assert h[0]["nota"] == "tipeo"


def test_borrar_precio_puede_revertir_el_karma_del_autor(client, admin, auth):
    lid = _local()
    uid = _mi_id(client, auth)
    pid = _cargar(client, auth, lid)
    antes = client.get("/v1/me", headers=auth).json()["karma"]
    r = client.delete(f"/v1/admin/precios/{pid}?revertir_karma=true&motivo=spam", headers=admin)
    assert r.status_code == 204
    assert client.get("/v1/me", headers=auth).json()["karma"] == antes - 1
    log = client.get(f"/v1/admin/auditoria?entidad=precio&entidad_id={pid}", headers=admin).json()
    assert "spam" in log["items"][0]["nota"] and "karma revertido" in log["items"][0]["nota"]
    # sin la opción, el karma queda
    pid2 = _cargar(client, auth, lid)
    k = client.get("/v1/me", headers=auth).json()["karma"]
    client.delete(f"/v1/admin/precios/{pid2}", headers=admin)
    assert client.get("/v1/me", headers=auth).json()["karma"] == k
    assert uid


def test_ficha_de_usuario_y_cambio_de_rol(client, admin):
    uid, _ = _registrado(client)
    f = client.get(f"/v1/admin/usuarios/{uid}", headers=admin).json()
    assert f["es_anonimo"] is False and f["rol"] == "usuario" and f["cargas_recientes"] == []

    r = client.post(
        f"/v1/admin/usuarios/{uid}/rol", headers=admin, json={"rol": "admin", "motivo": "socio"}
    )
    assert r.status_code == 200 and r.json()["rol"] == "admin"
    assert (
        client.post(
            f"/v1/admin/usuarios/{uid}/rol", headers=admin, json={"rol": "admin"}
        ).status_code
        == 409
    )  # ya lo es
    r = client.post(f"/v1/admin/usuarios/{uid}/rol", headers=admin, json={"rol": "usuario"})
    assert r.json()["rol"] == "usuario"
    h = client.get(f"/v1/admin/usuarios/{uid}", headers=admin).json()["historial"]
    assert [x["accion"] for x in h] == ["usuario.rol", "usuario.rol"]


def test_reglas_del_cambio_de_rol(client, admin, auth):
    yo = _mi_id(client, admin)
    anon = _mi_id(client, auth)
    assert (
        client.post(
            f"/v1/admin/usuarios/{yo}/rol", headers=admin, json={"rol": "usuario"}
        ).status_code
        == 409
    )  # no el propio
    assert (
        client.post(
            f"/v1/admin/usuarios/{anon}/rol", headers=admin, json={"rol": "admin"}
        ).status_code
        == 422
    )  # un anónimo no puede ser admin
    assert (
        client.post(
            f"/v1/admin/usuarios/{anon}/rol", headers=auth, json={"rol": "admin"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/admin/usuarios/{anon}/rol", headers=admin, json={"rol": "dios"}
        ).status_code
        == 422
    )


def test_ajustar_karma_exige_motivo_y_queda_auditado(client, admin, auth):
    uid = _mi_id(client, auth)
    k0 = client.get("/v1/me", headers=auth).json()["karma"]
    post = lambda body: client.post(  # noqa: E731
        f"/v1/admin/usuarios/{uid}/karma", headers=admin, json=body
    )
    assert post({"delta": 5}).status_code == 422
    assert post({"delta": 0, "motivo": "nada"}).status_code == 422
    r = post({"delta": 5, "motivo": "premio por aporte"})
    assert r.status_code == 200 and r.json()["karma"] == k0 + 5
    h = client.get(f"/v1/admin/usuarios/{uid}", headers=admin).json()["historial"][0]
    assert h["antes"] == {"karma": k0} and h["nota"] == "premio por aporte"


def test_ficha_de_producto_fuentes_conflictos_y_desbloqueo(client, admin):
    pid = str(_producto())
    sql(
        "insert into producto_fuentes (ean, fuente, datos) "
        "values ('7790000000017', 'off', '{\"nombre\": \"Adm Prod\"}'::jsonb) "
        "on conflict do nothing"
    )
    sql(
        "insert into conflictos_catalogo (ean, campo, valor_a, fuente_a, valor_b, fuente_b) "
        "values ('7790000000017', 'marca', 'Marca A', 'off', 'Marca B', 'sepa')"
    )
    f = client.get(f"/v1/admin/productos/{pid}", headers=admin).json()
    assert f["fuentes"][0]["datos"] == {"nombre": "Adm Prod"}
    assert f["conflictos"][0]["campo"] == "marca" and f["conflictos_pendientes"] == 1
    assert f["precios"] == 0

    client.patch(f"/v1/admin/productos/{pid}", headers=admin, json={"nombre": "Adm Fijo"})
    desb = lambda campos: client.post(  # noqa: E731
        f"/v1/admin/productos/{pid}/desbloquear", headers=admin, json={"campos": campos}
    )
    assert desb(["marca"]).status_code == 409  # no estaba bloqueado
    assert desb(["peso"]).status_code == 422
    r = desb(["nombre"])
    assert r.status_code == 200 and r.json()["campos_bloqueados"] == []
    # ya sin bloqueo, el ETL puede volver a tocarlo
    sql("update productos_canonicos set nombre = 'Pisado' where ean = '7790000000017'")
