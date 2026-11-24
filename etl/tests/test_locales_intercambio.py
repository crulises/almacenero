"""Intercambio de locales (docs/09 §8): exportar los verificados y sumarlos a otra base sin pisar
lo que ya existe. Contra Postgres local real; todo en Tierra del Fuego con nombres «Zz Test …»."""

import asyncio
import io
import zipfile

import pytest

from etl.comun.paquete import LEEME
from etl.locales_intercambio import FormatoInvalido, exportar, fila_a_local, importar, leer
from etl.tests.test_off_db import db

LAT, LNG = -54.31, -67.51


async def _limpiar(conn):
    await conn.execute("delete from locales where nombre like 'Zz Test%'")


@pytest.fixture(autouse=True)
def limpio_locales():
    db(_limpiar)
    yield
    db(_limpiar)


async def _sembrar(c):
    # A: verificado, de OSM, con vínculo y datos de pago
    a = await c.fetchval(
        "insert into locales (nombre, direccion, ubicacion, medios_pago, recargo_tarjeta, fuente,"
        " verificado) values ('Zz Test Almacén Uno', 'Calle 1', st_setsrid(st_makepoint($2, $1),"
        ' 4326)::geography, \'{"efectivo": true}\', \'{"aplica": true, "porcentaje": 10}\','
        " 'osm', true) returning id",
        LAT,
        LNG,
    )
    await c.execute(
        "insert into local_fuentes (local_id, fuente, ref, datos) values ($1, 'osm', 'node/9999',"
        " '{\"crudo\": 1}')",
        a,
    )
    # B: manual, verificado, sin vínculos
    await c.execute(
        "insert into locales (nombre, ubicacion, fuente, verificado) values ('Zz Test Kiosco',"
        " st_setsrid(st_makepoint($2, $1), 4326)::geography, 'manual', true)",
        LAT + 0.01,
        LNG,
    )
    # C: sin verificar
    await c.execute(
        "insert into locales (nombre, ubicacion, fuente, verificado) values ('Zz Test Dudoso',"
        " st_setsrid(st_makepoint($2, $1), 4326)::geography, 'sepa', false)",
        LAT + 0.02,
        LNG,
    )


def _locales():
    return db(
        lambda c: c.fetch(
            "select l.*, st_y(ubicacion::geometry) as lat, (select count(*) from local_fuentes f"
            " where f.local_id = l.id) as n from locales l where nombre like 'Zz Test%'"
            " order by nombre"
        )
    )


def test_exporta_solo_verificados_en_zip_con_leeme(tmp_path):
    db(_sembrar)
    ruta = tmp_path / "locales.zip"
    r = asyncio.run(exportar(ruta, prefijo_nombre="Zz Test"))
    assert (r.filas, r.verificados) == (2, 2)
    with zipfile.ZipFile(ruta) as z:
        assert z.namelist() == [LEEME, "locales.csv"]
        leeme = z.read(LEEME).decode()
    assert r.sha256 in leeme and "solo los verificados" in leeme and "ODbL" in leeme
    cabecera, filas, sha = leer(ruta)
    assert cabecera["formato"] == "locales_intercambio_v1" and sha == r.sha256
    por_nombre = {f["nombre"]: f for _, f in filas}
    assert set(por_nombre) == {"Zz Test Almacén Uno", "Zz Test Kiosco"}
    uno = por_nombre["Zz Test Almacén Uno"]
    assert uno["referencias"] == "osm:node/9999" and uno["fuente"] == "osm"
    assert '"efectivo": true' in uno["medios_pago"] and uno["verificado"] == "1"
    assert "crudo" not in "".join(uno.values())  # el dato crudo de la fuente no viaja
    # con todos
    r2 = asyncio.run(exportar(tmp_path / "t.zip", solo_verificados=False, prefijo_nombre="Zz Test"))
    assert (r2.filas, r2.verificados) == (3, 2)


def test_ida_y_vuelta_a_una_base_vacia_y_es_idempotente(tmp_path):
    db(_sembrar)
    ruta = tmp_path / "locales.zip"
    asyncio.run(exportar(ruta, prefijo_nombre="Zz Test"))
    antes = {(f["nombre"], f["fuente"], f["verificado"], f["n"]) for f in _locales()}
    db(_limpiar)  # «otra instalación»: base sin esos locales
    assert _locales() == []

    simulacro = asyncio.run(importar(ruta, aplicar=False))
    assert (simulacro.nuevos, simulacro.existentes) == (2, 0)
    assert _locales() == []  # el simulacro no escribe nada

    real = asyncio.run(importar(ruta, aplicar=True))
    assert (real.nuevos, real.existentes, real.vinculos_nuevos) == (2, 0, 1)
    despues = _locales()
    assert {(f["nombre"], f["fuente"], f["verificado"], f["n"]) for f in despues} == {
        a for a in antes if a[0] != "Zz Test Dudoso"
    }
    uno = next(f for f in despues if f["nombre"] == "Zz Test Almacén Uno")
    assert uno["creado_por"] is None and uno["direccion"] == "Calle 1"

    otra = asyncio.run(importar(ruta, aplicar=True))
    assert (otra.nuevos, otra.existentes, otra.vinculos_nuevos) == (0, 2, 0)
    assert len(_locales()) == 2


def test_un_local_existente_no_se_pisa_pero_se_verifica_y_se_vincula(tmp_path):
    db(_sembrar)
    ruta = tmp_path / "locales.zip"
    asyncio.run(exportar(ruta, prefijo_nombre="Zz Test"))
    db(_limpiar)

    # Acá el admin ya tenía el mismo local, corregido y sin verificar, sin vínculo
    async def previo(c):
        await c.execute(
            "insert into locales (nombre, direccion, ubicacion, fuente, verificado) values"
            " ('Zz Test Almacén Uno', 'Dirección corregida acá', st_setsrid(st_makepoint($2, $1),"
            " 4326)::geography, 'manual', false)",
            LAT + 0.00005,
            LNG,
        )

    db(previo)
    r = asyncio.run(importar(ruta, aplicar=True))
    assert (r.nuevos, r.existentes, r.verificados_ahora, r.vinculos_nuevos) == (1, 1, 1, 1)
    uno = next(f for f in _locales() if f["nombre"] == "Zz Test Almacén Uno")
    assert uno["direccion"] == "Dirección corregida acá"  # no se pisó
    assert uno["verificado"] is True and uno["n"] == 1 and uno["fuente"] == "manual"


def test_filas_invalidas_se_reportan_sin_frenar_el_resto(tmp_path):
    csv = (
        "# formato: locales_intercambio_v1\n"
        "id_origen,nombre,direccion,lat,lng,fuente,verificado,referencias,medios_pago,"
        "recargo_tarjeta\n"
        f"1,Zz Test Bueno,,{LAT},{LNG},manual,1,,,\n"
        f"2,X,,{LAT},{LNG},manual,1,,,\n"
        f"3,Zz Test Lejos,,95,{LNG},manual,1,,,\n"
        f"4,Zz Test Fuente,,{LAT},{LNG},facebook,1,,,\n"
        f"5,Zz Test Ref,,{LAT},{LNG},manual,1,tiktok:1,,\n"
        f"6,Zz Test Json,,{LAT},{LNG},manual,1,,[1],\n"
    )
    ruta = tmp_path / "l.csv"
    ruta.write_text(csv)
    r = asyncio.run(importar(ruta, aplicar=True))
    assert (r.leidas, r.nuevos) == (6, 1)
    assert dict(r.invalidas) == {
        "nombre_corto": 1,
        "coordenadas_fuera_de_rango": 1,
        "fuente_invalida": 1,
        "referencia_invalida": 1,
        "json_invalido": 1,
    }
    assert [f["nombre"] for f in _locales()] == ["Zz Test Bueno"]


def test_no_es_un_export_de_locales(tmp_path):
    ruta = tmp_path / "x.csv"
    ruta.write_text("# formato: catalogo_curado_v1\nean,nombre\n")
    with pytest.raises(FormatoInvalido, match="no es un export de locales"):
        asyncio.run(importar(ruta))
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("a.txt", b"x")
    ruta.write_bytes(z.getvalue())
    with pytest.raises(FormatoInvalido, match="ningún"):
        asyncio.run(importar(ruta))


def test_fila_a_local_acepta_valores_por_defecto():
    f = fila_a_local({"nombre": "Zz Test", "lat": "-54.3", "lng": "-67.5"})
    assert (f.fuente, f.verificado, f.referencias) == ("manual", False, ())
    assert f.recargo_tarjeta == {"aplica": False, "porcentaje": 0}
