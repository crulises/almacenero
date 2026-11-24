"""Eventos de producto (docs/04 §11.2): tabla genérica + registro de tipos + POST /v1/eventos.
Contra Postgres real."""

import asyncio

import asyncpg
import pytest

from app.config import get_settings
from app.services import eventos
from tests.db import sql


def _filas(user_id: str) -> list[asyncpg.Record]:
    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            return await conn.fetch(
                "select tipo, ocurrio_en, entidad, entidad_ref, datos::text as datos "
                "from eventos where usuario_id = $1::uuid order by id",
                user_id,
            )
        finally:
            await conn.close()

    return asyncio.run(run())


@pytest.fixture
def yo(client, auth):
    return client.get("/v1/me", headers=auth).json()["id"]


@pytest.fixture(autouse=True)
def _sin_rastros(auth):
    """Los tests comparten la base con el celular y con `make up`: cada test borra los eventos que
    creó (por usuario), para que no se confundan con los de verdad."""
    yield
    sql(
        "delete from eventos where usuario_id in "
        "(select id from usuarios where auth_id = $1::uuid)",
        _sub(auth["Authorization"].split()[1]),
    )


def _sub(token: str) -> str:
    import jwt

    return jwt.decode(token, options={"verify_signature": False})["sub"]


def _post(client, auth, lista):
    return client.post("/v1/eventos", json={"eventos": lista}, headers=auth)


def test_exige_login(client):
    assert client.post("/v1/eventos", json={"eventos": []}).status_code == 401


def test_guarda_un_escaneo_con_instante_del_servidor(client, auth, yo):
    r = _post(
        client,
        auth,
        [{"tipo": "producto.escaneado", "datos": {"ean": "7790070411112", "encontrado": True}}],
    )
    assert r.status_code == 201, r.text
    assert r.json() == {"guardados": 1}
    (f,) = _filas(yo)
    assert f["tipo"] == "producto.escaneado"
    assert f["entidad"] == "producto"
    assert f["entidad_ref"] == "7790070411112"
    assert f["ocurrio_en"].tzinfo is not None


def test_app_abierta_no_lleva_entidad(client, auth, yo):
    assert _post(client, auth, [{"tipo": "app.abierta"}]).status_code == 201
    (f,) = _filas(yo)
    assert (f["tipo"], f["entidad"], f["entidad_ref"]) == ("app.abierta", None, None)


def test_el_reloj_del_cliente_va_a_datos_y_no_a_ocurrio_en(client, auth, yo):
    r = _post(client, auth, [{"tipo": "app.abierta", "ocurrio_en_cliente": "2001-02-03T04:05:06Z"}])
    assert r.status_code == 201, r.text
    (f,) = _filas(yo)
    assert "2001-02-03" in f["datos"]
    assert f["ocurrio_en"].year >= 2026  # lo puso el servidor


def test_tipo_desconocido_da_400_con_la_regla(client, auth, yo):
    r = _post(client, auth, [{"tipo": "inventado.cualquiera"}])
    assert r.status_code == 400
    d = r.json()["detail"]
    assert d["codigo"] == "evento_tipo_desconocido"
    assert d["como_resolver"]
    assert _filas(yo) == []


def test_un_lote_con_un_tipo_malo_no_guarda_nada(client, auth, yo):
    r = _post(client, auth, [{"tipo": "app.abierta"}, {"tipo": "nope"}])
    assert r.status_code == 400
    assert _filas(yo) == []


def test_datos_invalidos_dan_422_con_la_regla(client, auth, yo):
    r = _post(
        client, auth, [{"tipo": "producto.escaneado", "datos": {"ean": "abc", "encontrado": True}}]
    )
    assert r.status_code == 422
    assert r.json()["detail"]["codigo"] == "evento_datos_invalidos"
    assert _filas(yo) == []


def test_datos_con_campos_de_mas_se_rechazan(client, auth, yo):
    """Privacidad: no entra texto libre ni ubicación aunque la app lo mande."""
    r = _post(
        client,
        auth,
        [
            {
                "tipo": "producto.escaneado",
                "datos": {"ean": "7790070411112", "encontrado": True, "lat": -34.6},
            }
        ],
    )
    assert r.status_code == 422
    assert _filas(yo) == []


def test_mas_de_50_se_rechaza(client, auth):
    r = _post(client, auth, [{"tipo": "app.abierta"}] * 51)
    assert r.status_code == 422


def test_un_tipo_solo_del_backend_no_lo_acepta_la_app(client, auth, yo, monkeypatch):
    monkeypatch.setitem(
        eventos.TIPOS,
        "solo.backend",
        eventos.TipoEvento(datos=eventos.DatosVacios, desde_app=False),
    )
    r = _post(client, auth, [{"tipo": "solo.backend"}])
    assert r.status_code == 400
    assert r.json()["detail"]["codigo"] == "evento_tipo_desconocido"


def test_rate_limit_por_usuario(client, auth, config_temporal):
    config_temporal("max_lotes_eventos_por_hora", "2")
    assert _post(client, auth, [{"tipo": "app.abierta"}]).status_code == 201
    assert _post(client, auth, [{"tipo": "app.abierta"}]).status_code == 201
    r = _post(client, auth, [{"tipo": "app.abierta"}])
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_el_usuario_borrado_deja_el_evento_huerfano(client, auth, yo):
    _post(client, auth, [{"tipo": "app.abierta", "datos": {"marca": "HuerfanoTest"}}])
    sql("delete from usuarios where id = $1::uuid", yo)
    n = asyncio.run(_contar_huerfanos())
    sql("delete from eventos where datos->>'marca' = 'HuerfanoTest'")
    assert n == 1


async def _contar_huerfanos() -> int:
    conn = await asyncpg.connect(get_settings().database_url)
    try:
        return await conn.fetchval(
            "select count(*) from eventos "
            "where usuario_id is null and datos->>'marca' = 'HuerfanoTest'"
        )
    finally:
        await conn.close()


def test_app_abierta_guarda_los_datos_del_dispositivo(client, auth, yo):
    datos = {
        "app_version": "0.1.0",
        "android": "14",
        "sdk": 34,
        "marca": "Google",
        "modelo": "Pixel 7",
        "idioma": "es-AR",
        "red": "wifi",
    }
    assert _post(client, auth, [{"tipo": "app.abierta", "datos": datos}]).status_code == 201
    (f,) = _filas(yo)
    assert '"modelo": "Pixel 7"' in f["datos"]
    assert '"red": "wifi"' in f["datos"]


def test_app_abierta_acepta_datos_parciales(client, auth, yo):
    """Si el celular no pudo leer algo, igual llega el resto (y los celulares con la app vieja)."""
    assert (
        _post(client, auth, [{"tipo": "app.abierta", "datos": {"idioma": "es"}}]).status_code == 201
    )


@pytest.mark.parametrize(
    "datos",
    [
        {"red": "satelite"},  # fuera de la lista
        {"ssid": "MiWifi"},  # nombre de la red: no
        {"lat": -34.6},  # ubicación: no
        {"modelo": "x" * 200},  # largo desmedido
    ],
)
def test_app_abierta_rechaza_lo_que_no_corresponde(client, auth, yo, datos):
    r = _post(client, auth, [{"tipo": "app.abierta", "datos": datos}])
    assert r.status_code == 422
    assert r.json()["detail"]["codigo"] == "evento_datos_invalidos"


@pytest.mark.parametrize("via", ["camara", "manual"])
def test_el_escaneo_dice_como_se_llego(client, auth, yo, via):
    r = _post(
        client,
        auth,
        [
            {
                "tipo": "producto.escaneado",
                "datos": {"ean": "7790070411113", "encontrado": False, "via": via},
            }
        ],
    )
    assert r.status_code == 201, r.text
    (f,) = _filas(yo)
    assert f'"via": "{via}"' in f["datos"]


def test_via_desconocida_se_rechaza(client, auth, yo):
    r = _post(
        client,
        auth,
        [
            {
                "tipo": "producto.escaneado",
                "datos": {"ean": "7790070411113", "encontrado": True, "via": "telepatia"},
            }
        ],
    )
    assert r.status_code == 422


def test_el_tipo_tiene_que_tener_formato(client):
    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            await conn.execute("insert into eventos (tipo) values ('Mal Tipo')")
        finally:
            await conn.close()

    with pytest.raises(asyncpg.CheckViolationError):
        asyncio.run(run())
