"""ETL de locales (OSM y sucursales de SEPA), contra Postgres local real.

Todo ocurre en Tierra del Fuego (sin datos reales cargados) y los locales de prueba se
llaman «Zz Test …»: se limpian solos.
"""

import io
import zipfile
from pathlib import Path

import osmium
import pytest

from etl.comun.locales import Local, ReporteLocales, fusionar_locales
from etl.osm.__main__ import cargar as cargar_osm
from etl.osm.__main__ import leer_pbf
from etl.sepa.locales import cargar as cargar_sepa
from etl.sepa.locales import nombre_local, transformar
from etl.tests.test_off_db import db

LAT, LNG = -54.30, -67.50  # dentro del cuadrado de prueba


async def _limpiar(conn):
    await conn.execute("delete from locales where nombre like 'Zz Test%'")


@pytest.fixture(autouse=True)
def limpio_locales():
    db(_limpiar)
    yield
    db(_limpiar)


def local(ref, nombre="Zz Test Almacen", lat=LAT, lng=LNG, fuente="osm"):
    return Local(fuente, ref, nombre, "Calle 1", lat, lng, {"x": 1})


def fusionar(*locales):
    reporte = ReporteLocales()

    async def f(conn):
        await fusionar_locales(conn, locales, reporte)

    db(f)
    return reporte


def locales_de_prueba():
    return db(
        lambda c: c.fetch(
            "select l.*, (select count(*) from local_fuentes f where f.local_id = l.id) as n"
            " from locales l where nombre like 'Zz Test%' order by nombre"
        )
    )


# ---------------------------------------------------------------- fusión común
def test_nuevo_local_entra_sin_verificar_y_sin_dueno():
    r = fusionar(local("node/1"))
    assert (r.nuevos, r.vinculados_a_existente, r.refrescados) == (1, 0, 0)
    (fila,) = locales_de_prueba()
    assert fila["verificado"] is False
    assert fila["creado_por"] is None
    assert fila["fuente"] == "osm"
    assert fila["n"] == 1


def test_idempotente_recargar_no_crea_nada():
    fusionar(local("node/1"))
    r = fusionar(local("node/1"))
    assert (r.nuevos, r.vinculados_a_existente, r.refrescados) == (0, 0, 1)
    assert len(locales_de_prueba()) == 1


def test_duplicado_de_otra_fuente_solo_agrega_el_vinculo():
    fusionar(local("node/1", fuente="osm"))
    # SEPA trae el mismo comercio a ~10 m, con el nombre casi igual
    r = fusionar(local("1-1-7", nombre="Zz Test Almacén", lat=LAT + 0.0001, fuente="sepa"))
    assert (r.nuevos, r.vinculados_a_existente) == (0, 1)
    (fila,) = locales_de_prueba()
    assert fila["fuente"] == "osm"  # el local conserva su origen
    assert fila["n"] == 2
    # y recargar SEPA no duplica el vínculo
    r = fusionar(local("1-1-7", nombre="Zz Test Almacén", lat=LAT + 0.0001, fuente="sepa"))
    assert r.refrescados == 1
    assert locales_de_prueba()[0]["n"] == 2


def test_nombre_distinto_o_lejos_no_es_duplicado():
    fusionar(local("node/1"))
    fusionar(local("node/2", nombre="Zz Test Ferreteria"))  # mismo lugar, otro comercio
    fusionar(local("node/3", lat=LAT + 0.01))  # mismo nombre, a ~1 km
    assert len(locales_de_prueba()) == 3


def test_local_editado_por_el_admin_no_se_pisa_al_recargar():
    fusionar(local("node/1"))
    db(
        lambda c: c.execute(
            "update locales set nombre = 'Zz Test Corregido' where nombre like 'Zz Test%'"
        )
    )
    fusionar(local("node/1"))
    assert [f["nombre"] for f in locales_de_prueba()] == ["Zz Test Corregido"]


# ------------------------------------------------------------------------ SEPA
CABECERA_SUC = "|".join(
    ["id_comercio", "id_bandera", "id_sucursal", "sucursales_nombre", "sucursales_tipo"]
    + ["sucursales_calle", "sucursales_numero", "sucursales_latitud", "sucursales_longitud"]
    + ["sucursales_localidad", "sucursales_provincia"]
)


def zip_sepa_locales(tmp_path: Path, *filas: str) -> Path:
    interno = io.BytesIO()
    with zipfile.ZipFile(interno, "w") as z:
        z.writestr(
            "comercio.csv",
            "id_comercio|id_bandera|comercio_bandera_nombre\n9|1|Zz Test Super\n",
        )
        z.writestr("sucursales.csv", ("﻿" + "\n".join([CABECERA_SUC, *filas]) + "\n").encode())
    ruta = tmp_path / "sepa.zip"
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("2026-11-15/sepa_1_comercio-sepa-9.zip", interno.getvalue())
        z.writestr("2026-11-15/sepa_1_comercio-sepa-8.zip", b"")  # zip interno vacío (pasa)
    return ruta


def suc(n, nombre, calle="Av. Test", lat=LAT, lng=LNG, prov="AR-V", numero="123"):
    return f"9|1|{n}|{nombre}|Supermercado|{calle}|{numero}|{lat}|{lng}|Ushuaia|{prov}"


def test_nombre_de_sucursal():
    assert nombre_local("CARREFOUR", "Sucursal 3") == "Carrefour"
    assert nombre_local("Dia", "Local 12") == "Dia"
    assert nombre_local("Coto", "ACASSUSO") == "Coto Acassuso"
    assert nombre_local("Coto", "Coto Centro") == "Coto Centro"


def test_sepa_filtra_por_nombre_calle_y_coordenadas(tmp_path):
    ruta = zip_sepa_locales(
        tmp_path,
        suc(1, "Sucursal 1"),  # entra, como la bandera sola
        suc(2, "Centro", lat=LAT + 0.01),  # entra: «Zz Test Super Centro»
        suc(3, "Sin calle", calle=""),
        suc(4, "Sin coordenadas", lat="", lng=""),
        suc(5, "Basura", lat="0", lng="0"),
        suc(6, "Otra provincia", prov="AR-N"),
        suc(7, "Sin numero", numero="", lat=LAT + 0.02),  # el número no hace falta
    )
    r = db_cargar_sepa(ruta, "tierra-del-fuego")
    assert r.leidos == 7
    assert r.nuevos == 3
    assert dict(r.descartados) == {
        "sin_calle": 1,
        "sin_coordenadas": 2,
        "otra_provincia": 1,
        "zip_interno_invalido": 1,
    }
    assert [f["nombre"] for f in locales_de_prueba()] == [
        "Zz Test Super",
        "Zz Test Super Centro",
        "Zz Test Super Sin numero",
    ]
    fuentes = db(
        lambda c: c.fetchval(
            "select array_agg(distinct fuente) from locales where nombre like 'Zz Test%'"
        )
    )
    assert fuentes == ["sepa"]


def db_cargar_sepa(ruta, provincia):
    import asyncio

    return asyncio.run(cargar_sepa([ruta], provincia))


def test_transformar_sepa_guarda_la_referencia():
    reporte = ReporteLocales()
    fila = {
        "id_comercio": "9",
        "id_bandera": "1",
        "id_sucursal": "44",
        "bandera": "Zz Test Super",
        "sucursales_nombre": "Sucursal 44",
        "sucursales_calle": "AV. LIBERTADOR",
        "sucursales_numero": "15301",
        "sucursales_latitud": "-34,47436",
        "sucursales_longitud": "-58,50185",
        "sucursales_localidad": "ACASSUSO",
        "sucursales_provincia": "AR-B",
    }
    loc = transformar(fila, reporte, None)
    assert loc is not None
    assert loc.ref == "9-1-44"
    assert loc.direccion == "Av. Libertador 15301, Acassuso"
    assert (loc.lat, loc.lng) == (-34.47436, -58.50185)


# ------------------------------------------------------------------------- OSM
def escribir_pbf(ruta: Path) -> None:
    """Un mini extracto: la «provincia» AR-V como cuadrado y cuatro comercios."""
    from osmium.osm.mutable import Node, Relation, Way

    w = osmium.SimpleWriter(str(ruta))
    esquinas = [(1, -68.0, -54.5), (2, -67.0, -54.5), (3, -67.0, -54.0), (4, -68.0, -54.0)]
    for i, lng, lat in esquinas:
        w.add_node(Node(id=i, location=(lng, lat)))
    # un edificio chico mapeado como camino cerrado, adentro
    edif = [(11, -67.60, -54.40), (12, -67.59, -54.40), (13, -67.59, -54.39), (14, -67.60, -54.39)]
    for i, lng, lat in edif:
        w.add_node(Node(id=i, location=(lng, lat)))
    shop = {"shop": "supermarket", "name": "Zz Test OSM", "addr:street": "Calle OSM"}
    w.add_node(Node(id=100, location=(LNG, LAT), tags={**shop, "addr:housenumber": "5"}))
    w.add_node(
        Node(
            id=101,
            location=(LNG, LAT + 0.05),
            tags={"shop": "convenience", "name": "Zz Test Sin Calle"},
        )
    )
    w.add_node(
        Node(
            id=102,
            location=(LNG, LAT + 0.06),
            tags={"shop": "convenience", "addr:street": "Calle X"},
        )
    )
    w.add_node(Node(id=103, location=(-60.0, -30.0), tags={**shop, "name": "Zz Test Lejos"}))
    w.add_node(
        Node(
            id=104,
            location=(LNG, LAT + 0.07),
            tags={"shop": "bakery", "name": "Zz Test Panaderia", "addr:street": "Y"},
        )
    )
    w.add_way(Way(id=200, nodes=[1, 2, 3, 4, 1], tags={}))
    w.add_way(Way(id=201, nodes=[11, 12, 13, 14, 11], tags={**shop, "name": "Zz Test Edificio"}))
    w.add_relation(
        Relation(
            id=300,
            members=[("w", 200, "outer")],
            tags={
                "type": "boundary",
                "boundary": "administrative",
                "admin_level": "4",
                "ISO3166-2": "AR-V",
                "name": "Tierra del Fuego",
            },
        )
    )
    w.close()


def test_leer_pbf_encuentra_comercios_y_limite(tmp_path):
    ruta = tmp_path / "mini.osm.pbf"
    escribir_pbf(ruta)
    lectura = leer_pbf(ruta, "AR-V")
    assert lectura.limite_wkt and lectura.limite_wkt.startswith("MULTIPOLYGON")
    ids = {(c.tipo, c.osm_id) for c in lectura.comercios}
    assert ids == {("node", 100), ("node", 101), ("node", 102), ("node", 103), ("way", 201)}
    edificio = next(c for c in lectura.comercios if c.osm_id == 201)
    assert edificio.lat == pytest.approx(-54.395)
    assert leer_pbf(ruta, "AR-N").limite_wkt is None  # otra provincia: sin límite


def test_cargar_osm_exige_nombre_y_calle_dentro_de_la_provincia(tmp_path):
    import asyncio

    ruta = tmp_path / "mini.osm.pbf"
    escribir_pbf(ruta)
    r = asyncio.run(cargar_osm(ruta, "tierra-del-fuego"))
    # adentro: 100 (ok), 101 (sin calle), 102 (sin nombre), 201 (edificio, ok); 103 está lejos
    assert r.leidos == 4
    assert r.nuevos == 2
    assert dict(r.descartados) == {"sin_calle": 1, "sin_nombre": 1}
    nombres = [f["nombre"] for f in locales_de_prueba()]
    assert nombres == ["Zz Test Edificio", "Zz Test OSM"]
    direccion = db(
        lambda c: c.fetchval("select direccion from locales where nombre = 'Zz Test OSM'")
    )
    assert direccion == "Calle OSM 5"
    refs = db(
        lambda c: c.fetch(
            "select ref from local_fuentes where ref like 'node/%' or ref like 'way/%' order by ref"
        )
    )
    assert {f["ref"] for f in refs} >= {"node/100", "way/201"}
    # recargar el mismo archivo no cambia nada
    r2 = asyncio.run(cargar_osm(ruta, "tierra-del-fuego"))
    assert (r2.nuevos, r2.vinculados_a_existente, r2.refrescados) == (0, 0, 2)
