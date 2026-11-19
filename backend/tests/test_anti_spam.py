"""Anti-spam (docs/04 §6): invitaciones, rate limit por IP, límites por usuario y
karma por duplicados. Postgres real; el proveedor de auth, simulado."""

import uuid

import httpx
import pytest

from app.config import get_settings
from app.main import app
from app.services.ratelimit import LimitadorVentana
from tests.conftest import make_token
from tests.db import cuerpo_carga, sql

SESION = {"access_token": "acc", "refresh_token": "ref", "expires_in": 3600}
EAN = "7790070411112"


@pytest.fixture
def proveedor(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "auth_url", "http://auth.test/auth/v1")
    monkeypatch.setattr(s, "auth_api_key", "clave-publica")
    estado = {"status": 200, "llamadas": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        estado["llamadas"] += 1
        return httpx.Response(estado["status"], json=SESION if estado["status"] == 200 else {})

    original = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    yield estado
    app.state.http = original


@pytest.fixture
def invitacion():
    """Crea una invitación de prueba y las borra al final."""

    def crear(usos_max=None, vence="null") -> str:
        codigo = f"test-{uuid.uuid4().hex[:8]}"
        sql(
            f"insert into invitaciones (codigo, usos_max, vence, nota) "
            f"values ($1, $2, {vence}, 'test')",
            codigo,
            usos_max,
        )
        return codigo

    yield crear
    sql("delete from invitaciones where nota = 'test'")


def _alta(client, codigo=None):
    return client.post("/v1/auth/anonymous", json={"codigo_invitacion": codigo} if codigo else None)


def _usos(codigo: str) -> int:
    import asyncio

    import asyncpg

    async def run():
        c = await asyncpg.connect(get_settings().database_url)
        try:
            return await c.fetchval("select usos from invitaciones where codigo = $1", codigo)
        finally:
            await c.close()

    return asyncio.run(run())


# ---------------------------------------------------------------- modo_acceso
def test_solo_invitacion_exige_codigo(client, proveedor, config_temporal):
    config_temporal("modo_acceso", '"solo_invitacion"')
    r = _alta(client)
    assert r.status_code == 403
    assert r.json()["detail"]["codigo"] == "invitacion_requerida"
    assert proveedor["llamadas"] == 0  # ni se molestó al proveedor


def test_codigo_valido_crea_sesion_y_gasta_un_uso(client, proveedor, config_temporal, invitacion):
    config_temporal("modo_acceso", '"solo_invitacion"')
    codigo = invitacion()
    assert _alta(client, codigo).status_code == 200
    assert _usos(codigo) == 1


def test_el_codigo_no_distingue_mayusculas_ni_espacios(
    client, proveedor, config_temporal, invitacion
):
    config_temporal("modo_acceso", '"solo_invitacion"')
    codigo = invitacion()
    assert _alta(client, f"  {codigo.upper()} ").status_code == 200


def test_codigo_inexistente_403(client, proveedor, config_temporal):
    config_temporal("modo_acceso", '"solo_invitacion"')
    r = _alta(client, "no-existe")
    assert r.status_code == 403
    assert r.json()["detail"]["codigo"] == "invitacion_invalida"


def test_codigo_vencido_403(client, proveedor, config_temporal, invitacion):
    config_temporal("modo_acceso", '"solo_invitacion"')
    codigo = invitacion(vence="now() - interval '1 minute'")
    assert _alta(client, codigo).status_code == 403


def test_tope_de_usos(client, proveedor, config_temporal, invitacion):
    config_temporal("modo_acceso", '"solo_invitacion"')
    codigo = invitacion(usos_max=2)
    assert _alta(client, codigo).status_code == 200
    assert _alta(client, codigo).status_code == 200
    assert _alta(client, codigo).status_code == 403
    assert _usos(codigo) == 2


def test_si_el_proveedor_falla_no_se_gasta_la_invitacion(
    client, proveedor, config_temporal, invitacion
):
    config_temporal("modo_acceso", '"solo_invitacion"')
    codigo = invitacion(usos_max=1)
    proveedor["status"] = 500
    assert _alta(client, codigo).status_code == 502
    assert _usos(codigo) == 0
    proveedor["status"] = 200
    assert _alta(client, codigo).status_code == 200


def test_modo_abierto_no_pide_codigo(client, proveedor, config_temporal):
    config_temporal("modo_acceso", '"abierto"')
    assert _alta(client).status_code == 200


def test_alta_manual_cierra_las_altas_aun_con_codigo(
    client, proveedor, config_temporal, invitacion
):
    config_temporal("modo_acceso", '"alta_manual"')
    r = _alta(client, invitacion())
    assert r.status_code == 403
    assert r.json()["detail"]["codigo"] == "alta_cerrada"


def test_la_base_rechaza_codigos_sin_normalizar_y_usos_de_mas():
    with pytest.raises(Exception, match="check"):
        sql("insert into invitaciones (codigo) values ('MAYUS')")
    with pytest.raises(Exception, match="check"):
        sql("insert into invitaciones (codigo, usos_max, usos) values ('test-x', 1, 2)")


# ----------------------------------------------------------------- rate limit
def test_rate_limit_de_altas_por_ip(client, proveedor, config_temporal):
    config_temporal("modo_acceso", '"abierto"')
    config_temporal("auth_altas_por_hora_ip", "3")
    assert [_alta(client).status_code for _ in range(3)] == [200, 200, 200]
    r = _alta(client)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1
    assert r.json()["detail"]["codigo"] == "demasiados_intentos"


def test_los_codigos_malos_tambien_cuentan(client, proveedor, config_temporal):
    config_temporal("modo_acceso", '"solo_invitacion"')
    config_temporal("auth_altas_por_hora_ip", "2")
    assert _alta(client, "a").status_code == 403
    assert _alta(client, "b").status_code == 403
    assert _alta(client, "c").status_code == 429


def test_rate_limit_de_refresh(client, proveedor, config_temporal):
    config_temporal("auth_refresh_por_hora_ip", "2")
    for _ in range(2):
        assert client.post("/v1/auth/refresh", json={"refresh_token": "r"}).status_code == 200
    assert client.post("/v1/auth/refresh", json={"refresh_token": "r"}).status_code == 429


def test_la_ip_sale_del_proxy_confiable(client, proveedor, config_temporal, monkeypatch):
    config_temporal("modo_acceso", '"abierto"')
    config_temporal("auth_altas_por_hora_ip", "1")
    monkeypatch.setattr(get_settings(), "proxy_hops", 1)

    def alta(xff: str):
        return client.post("/v1/auth/anonymous", headers={"X-Forwarded-For": xff})

    # lo que escribe el cliente a la izquierda se ignora: cuenta la IP que vio el proxy
    assert alta("9.9.9.9, 1.1.1.1").status_code == 200
    assert alta("8.8.8.8, 1.1.1.1").status_code == 429
    assert alta("8.8.8.8, 2.2.2.2").status_code == 200


def test_ventana_deslizante_libera_cupo_con_el_tiempo():
    lim = LimitadorVentana()
    assert lim.intentar("k", 2, 100, ahora=0) is None
    assert lim.intentar("k", 2, 100, ahora=10) is None
    assert lim.intentar("k", 2, 100, ahora=20) == 80  # espera hasta que venza el primero
    assert lim.intentar("k", 2, 100, ahora=101) is None
    assert lim.intentar("otra", 2, 100, ahora=20) is None


# ---------------------------------------------------------- límites por usuario
def _local_id(client, auth) -> str:
    return client.get("/v1/locales", headers=auth).json()[0]["id"]


def _cargar(client, auth, precio):
    return client.post(
        "/v1/precios", headers=auth, json=cuerpo_carga(_local_id(client, auth), EAN, precio)
    )


def test_tope_de_cargas_por_hora(client, auth, config_temporal):
    config_temporal("max_precios_por_hora", "2")
    assert _cargar(client, auth, "101").status_code == 201
    assert _cargar(client, auth, "102").status_code == 201
    r = _cargar(client, auth, "103")
    assert r.status_code == 429
    assert r.json()["detail"]["codigo"] == "limite_cargas"
    # el tope es por usuario: otro sigue cargando
    otro = {"Authorization": f"Bearer {make_token()}"}
    assert _cargar(client, otro, "101").status_code == 201


def test_tope_de_cargas_por_dia(client, auth, config_temporal):
    config_temporal("max_precios_por_dia", "1")
    assert _cargar(client, auth, "101").status_code == 201
    assert _cargar(client, auth, "102").status_code == 429


# --------------------------------------------------------------- karma duplicado
def test_repetir_el_mismo_precio_no_suma_karma(client, auth):
    primera = _cargar(client, auth, "250.00").json()
    assert (primera["karma"], primera["karma_sumado"]) == (1, 1)
    repetida = _cargar(client, auth, "250.00")
    assert repetida.status_code == 201  # el precio se guarda igual: confirma vigencia
    assert (repetida.json()["karma"], repetida.json()["karma_sumado"]) == (1, 0)
    otro_precio = _cargar(client, auth, "260.00").json()
    assert (otro_precio["karma"], otro_precio["karma_sumado"]) == (2, 1)


def test_otro_usuario_si_suma_karma_por_el_mismo_precio(client, auth):
    _cargar(client, auth, "270.00")
    otro = {"Authorization": f"Bearer {make_token()}"}
    assert _cargar(client, otro, "270.00").json()["karma_sumado"] == 1
