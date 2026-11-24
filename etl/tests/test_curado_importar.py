"""Importador del CSV curado contra Postgres local real (sin mocks de la base)."""

import asyncio
import json

import pytest

from etl.comun.normalizar import NORMALIZADOR_VERSION
from etl.curado.exportar import exportar
from etl.curado.formato import COLUMNAS, escribir
from etl.curado.importar import importar
from etl.tests.test_off_db import csv_off, db, ean, fila, insertar_manual, limpio, producto  # noqa: F401
from etl.tests.test_sepa_db import fila_sepa, zip_sepa


@pytest.fixture(autouse=True)
def lotes_limpios():
    borrar = lambda c: c.execute("delete from catalogo_lotes where nombre_archivo like 'test-%'")  # noqa: E731
    db(borrar)
    yield
    db(borrar)


def f(e, nombre, **kw):
    base = dict.fromkeys(COLUMNAS, "")
    base.update(ean=e, nombre=nombre, fuente_origen="sepa", **kw)
    return base


def csv_curado(tmp_path, *filas, nombre="test-curado.csv"):
    ruta = tmp_path / nombre
    escribir(ruta, filas, {"normalizador": str(NORMALIZADOR_VERSION)})
    return ruta


def correr(ruta, **kw):
    return asyncio.run(importar(ruta, **kw))


def cuenta(tabla="productos_canonicos"):
    return db(lambda c: c.fetchval(f"select count(*) from {tabla} where ean like '79999%'"))


def lotes():
    return db(lambda c: c.fetch("select * from catalogo_lotes where nombre_archivo like 'test-%'"))


def test_simulacro_informa_y_no_escribe(tmp_path):
    a, b = ean(1), ean(2)
    insertar_manual(b, "Fideos viejos", "Lucchetti")
    ruta = csv_curado(
        tmp_path,
        f(a, "Aceite Girasol", marca="Cocinero", tamano_valor="900", tamano_unidad="ml"),
        f(b, "Fideos Tirabuzón", marca="Lucchetti"),
        f("123", "EAN corto"),
    )
    antes = cuenta()
    r = correr(ruta, aplicar=False)
    assert (r.leidas, r.validas, r.nuevos) == (3, 2, 1)
    assert r.invalidas == {"ean_largo_invalido": 1}
    assert r.ejemplos_invalidos[0][0] > 0  # número de línea
    assert cuenta() == antes and cuenta("producto_fuentes") == 0 and lotes() == []


def test_aplicar_escribe_y_registra_el_lote(tmp_path):
    a = ean(1)
    ruta = csv_curado(
        tmp_path, f(a, "Aceite Girasol", marca="Cocinero", tamano_valor="900", tamano_unidad="ml")
    )
    r = correr(ruta, aplicar=True)
    p = producto(a)
    assert (p["nombre"], p["origen"], p["estado_calidad"] is not None) == (
        "Aceite Girasol",
        "curado",
        True,
    )
    fuente = db(lambda c: c.fetchrow("select * from producto_fuentes where ean = $1", a))
    assert fuente["fuente"] == "curado"
    datos = json.loads(fuente["datos"])
    assert datos["fuente_origen"] == "sepa" and datos["archivo_sha256"] == r.sha256
    (lote,) = lotes()
    assert (lote["sha256"], lote["filas"], lote["nuevos"], lote["invalidos"]) == (r.sha256, 1, 1, 0)
    assert lote["version_normalizador"] == NORMALIZADOR_VERSION and lote["id"] == r.lote_id
    assert lote["formato"] == "catalogo_curado_v1"


def test_reimportar_es_idempotente(tmp_path):
    ruta = csv_curado(tmp_path, f(ean(1), "Aceite Girasol"))
    correr(ruta, aplicar=True)
    r2 = correr(ruta, aplicar=True)
    assert r2.ya_importado and r2.lote_id is None and len(lotes()) == 1
    r3 = correr(ruta, aplicar=True, forzar=True)
    assert (r3.nuevos, r3.cambiados, r3.iguales) == (0, 0, 1) and len(lotes()) == 2


def test_duplicados_gana_el_ultimo(tmp_path):
    a = ean(1)
    ruta = csv_curado(tmp_path, f(a, "Primero Nombre"), f(a, "Segundo Nombre"))
    r = correr(ruta, aplicar=True)
    assert r.duplicados == 1 and r.validas == 1
    assert producto(a)["nombre"] == "Segundo Nombre"


def test_curado_pisa_sepa_y_muestra_el_cambio(tmp_path):
    a = ean(1)
    db(
        lambda c: c.execute(
            "insert into productos_canonicos (ean, nombre, marca, origen)"
            " values ($1, 'Aceite NUCETE bot', 'Nucete', 'sepa')",
            a,
        )
    )
    ruta = csv_curado(tmp_path, f(a, "Aceite de Oliva", marca="Nucete"))
    r = correr(ruta, aplicar=False)
    assert (r.cambiados, r.nuevos) == (1, 0)
    assert r.ejemplos_cambios[0]["ean"] == a
    assert r.ejemplos_cambios[0]["cambios"]["nombre"] == ["Aceite NUCETE bot", "Aceite de Oliva"]
    correr(ruta, aplicar=True)
    assert producto(a)["origen"] == "curado"


def test_respeta_campos_bloqueados_y_origen_manual(tmp_path):
    a = ean(1)

    async def preparar(c):
        async with c.transaction():
            await c.execute("select set_config('app.catalogo_write', 'on', true)")
            await c.execute(
                "insert into productos_canonicos (ean, nombre, marca, origen, campos_bloqueados)"
                " values ($1, 'Nombre del admin', 'Vieja', 'manual', array['nombre'])",
                a,
            )

    db(preparar)
    correr(csv_curado(tmp_path, f(a, "Otro Nombre Distinto", marca="Marca Nueva")), aplicar=True)
    p = producto(a)
    assert (p["nombre"], p["origen"]) == ("Nombre del admin", "manual")


def test_archivo_editado_a_mano_se_avisa(tmp_path):
    ruta = csv_curado(tmp_path, f(ean(1), "Aceite Girasol"))
    ruta.write_text(ruta.read_text().replace("Girasol", "Maíz"), encoding="utf-8")
    r = correr(ruta, aplicar=False)
    assert r.editado and "editado" in r.texto()


def test_exportar_e_importar_cierra_el_circulo(tmp_path):
    off = csv_off(tmp_path, fila(ean(1), "Aceite de Girasol", "Cocinero", "900 ml"))
    sepa = zip_sepa(tmp_path, fila_sepa(ean(2), "FIDEOS TIRABUZON", "500", "gr", "LUCCHETTI"))
    ruta = tmp_path / "test-circulo.csv.gz"
    exportar(ruta, off=off, sepa=[sepa])
    r = correr(ruta, aplicar=True)
    assert (r.nuevos, r.invalidas.total()) == (2, 0)
    lote = lotes()[0]
    assert "csv" in lote["fuentes_entrada"] and lote["sha256"] == r.sha256
    r2 = correr(ruta, aplicar=False)  # dry-run sobre lo ya cargado: nada cambia
    assert (r2.nuevos, r2.cambiados, r2.iguales) == (0, 0, 2)


def test_archivo_ajeno_da_error_claro(tmp_path):
    ruta = tmp_path / "test-x.csv"
    ruta.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="formato"):
        correr(ruta, aplicar=False)


def test_cambiar_solo_la_fuente_no_cuenta_como_cambio_de_datos(tmp_path):
    a = ean(1)
    db(
        lambda c: c.execute(
            "insert into productos_canonicos (ean, nombre, marca, origen)"
            " values ($1, 'Aceite Girasol', 'Cocinero', 'sepa')",
            a,
        )
    )
    r = correr(csv_curado(tmp_path, f(a, "Aceite Girasol", marca="Cocinero")), aplicar=True)
    assert (r.cambiados, r.iguales, r.cambia_origen) == (0, 1, 1), r.ejemplos_cambios
    assert producto(a)["origen"] == "curado"
    assert "pasan a figurar como `curado`: 1" in r.texto()
