# ruff: noqa: E501
"""Exportador del CSV curado: arma el archivo desde las fuentes crudas, sin base de datos."""

import hashlib
from decimal import Decimal

from etl.comun.catalogo import Producto, normalizar_producto
from etl.curado.exportar import exportar
from etl.curado.formato import fila_a_producto, leer
from etl.tests.test_off_db import csv_off, ean, fila
from etl.tests.test_sepa_db import fila_sepa, zip_sepa


def fuentes(tmp_path):
    a, b, c = ean(1), ean(2), ean(3)
    off = csv_off(
        tmp_path,
        fila(a, "Aceite de Girasol Cocinero 900 ml", "Cocinero", "900 ml", img="https://img/a.jpg"),
        fila(b, "Fideos Tirabuzón", "Lucchetti", "500 g"),
        fila(c, "Yerba de otro país", "X", "1 kg", paises="en:france"),
        fila("7790070411113", "Mal dígito", "M", "1 kg"),
    )
    sepa = zip_sepa(
        tmp_path,
        fila_sepa(a, "ACEITE GIRASOL COCINERO", "900", "ml", "COCINERO", sucursal="1"),
        fila_sepa(a, "ACEITE GIRASOL COCINERO", "900", "ml", "COCINERO", sucursal="2"),
        fila_sepa(ean(4), "GALLETITAS", "300", "gr", "TERRABUSI", sucursal="1"),
    )
    return a, b, c, off, sepa


def productos(ruta):
    return {f["ean"]: f for _, f in leer(ruta).filas}


def test_dos_corridas_dan_el_mismo_hash(tmp_path):
    *_, off, sepa = fuentes(tmp_path)
    r1 = exportar(tmp_path / "1.csv", off=off, sepa=[sepa], paises=None)
    r2 = exportar(tmp_path / "2.csv", off=off, sepa=[sepa], paises=None)
    assert r1.sha256 == r2.sha256 == leer(tmp_path / "2.csv").sha256


def test_sepa_gana_y_off_completa(tmp_path):
    a, *_, off, sepa = fuentes(tmp_path)
    exportar(tmp_path / "c.csv", off=off, sepa=[sepa], paises=None)
    f = productos(tmp_path / "c.csv")[a]
    assert f["nombre"] == "Aceite Girasol"  # el de SEPA, ya normalizado (marca y tamaño afuera)
    assert f["imagen_url"] == "https://img/a.jpg"  # lo que solo trae OFF
    assert f["fuente_origen"] == "sepa+off"
    assert (f["tamano_valor"], f["tamano_unidad"]) == ("900", "ml")


def test_filtro_de_paises_y_descartes(tmp_path):
    a, b, c, off, sepa = fuentes(tmp_path)
    r = exportar(tmp_path / "c.csv", off=off, sepa=[sepa], paises=frozenset({"en:argentina"}))
    filas = productos(tmp_path / "c.csv")
    assert c not in filas and b in filas
    assert r.descartadas["fuera_de_paises"] == 1 and r.descartadas["ean_digito_verificador"] == 1
    assert r.filas == len(filas) == 3
    assert r.por_origen == {"sepa+off": 1, "off": 1, "sepa": 1}


def test_sepa_min_filas(tmp_path):
    a, *_, off, sepa = fuentes(tmp_path)
    exportar(tmp_path / "c.csv", off=None, sepa=[sepa], paises=None, sepa_min_filas=2)
    assert list(productos(tmp_path / "c.csv")) == [a]  # solo el que informan 2 sucursales


def test_cabecera_con_hash_de_las_fuentes_y_version(tmp_path):
    *_, off, sepa = fuentes(tmp_path)
    exportar(tmp_path / "c.csv", off=off, sepa=[sepa], paises=None)
    cab = leer(tmp_path / "c.csv").cabecera
    assert cab["normalizador"] == "1"
    assert f"{off.name}:{hashlib.sha256(off.read_bytes()).hexdigest()}" in cab["fuentes"]
    assert f"{sepa.name}:{hashlib.sha256(sepa.read_bytes()).hexdigest()}" in cab["fuentes"]


def test_cada_fila_es_punto_fijo_del_normalizador(tmp_path):
    *_, off, sepa = fuentes(tmp_path)
    exportar(tmp_path / "c.csv", off=off, sepa=[sepa], paises=None)
    for _, f in leer(tmp_path / "c.csv").filas:
        p = fila_a_producto(f)
        n, _ = normalizar_producto(p)
        assert (n.nombre, n.marca, n.tamano_valor, n.tamano_unidad, n.pack_cantidad) == (
            p.nombre,
            p.marca,
            p.tamano_valor,
            p.tamano_unidad,
            p.pack_cantidad,
        )
        assert isinstance(p, Producto) and p.tamano_valor in (None, p.tamano_valor)
        assert p.tamano_valor is None or p.tamano_valor > Decimal(0)


def test_el_zip_trae_el_csv_y_un_leeme_con_las_reglas_aplicadas(tmp_path):
    import zipfile

    from etl.comun.paquete import LEEME

    a, *_, off, sepa = fuentes(tmp_path)
    r = exportar(tmp_path / "armado.zip", off=off, sepa=[sepa], paises=None)
    with zipfile.ZipFile(tmp_path / "armado.zip") as z:
        assert z.namelist() == [LEEME, "armado.csv"]
        leeme = z.read(LEEME).decode()
    assert r.sha256 in leeme
    assert "Qué se hizo con los datos" in leeme and "Transformaciones" in leeme
    assert "Cómo importarlo" in leeme and "Columnas" in leeme
    # el reporte del log cuenta lo mismo que el LEEME
    assert r.reglas and r.reglas in leeme
    # y el zip se lee igual que el csv: mismo hash de contenido
    assert productos(tmp_path / "armado.zip")[a]["nombre"] == "Aceite Girasol"
    exportar(tmp_path / "armado.csv", off=off, sepa=[sepa], paises=None)
    assert leer(tmp_path / "armado.zip").sha256 == leer(tmp_path / "armado.csv").sha256
