"""Formato `catalogo_curado_v1` (docs/04 §10-B): validación fila a fila y archivo reproducible."""

import gzip
from decimal import Decimal

import pytest

from etl.comun.catalogo import Producto
from etl.curado.formato import (
    COLUMNAS,
    COLUMNAS_V2,
    FORMATO,
    FORMATO_V2,
    FilaInvalida,
    FormatoInvalido,
    escribir,
    fila_a_producto,
    leer,
    meta_de_fila,
    producto_a_fila,
)

EAN = "7790070411112"


def fila(**kw):
    base = dict.fromkeys(COLUMNAS, "")
    base.update(ean=EAN, nombre="Aceite de Girasol", marca="Cocinero")
    base.update(kw)
    return base


def test_fila_valida_a_producto():
    p = fila_a_producto(
        fila(
            tamano_valor="900",
            tamano_unidad="ml",
            pack_cantidad="6",
            presentacion="botella",
            fuente_origen="sepa",
            nota="a mano",
        )
    )
    assert (p.ean, p.nombre, p.marca) == (EAN, "Aceite de Girasol", "Cocinero")
    assert (p.tamano_valor, p.tamano_unidad, p.pack_cantidad) == (Decimal(900), "ml", 6)
    assert '"fuente_origen": "sepa"' in p.datos and '"nota": "a mano"' in p.datos


@pytest.mark.parametrize(
    ("cambios", "motivo"),
    [
        ({"ean": "123"}, "ean_largo_invalido"),
        ({"ean": "7790070411113"}, "ean_digito_verificador"),
        ({"nombre": " x "}, "nombre_corto"),
        ({"tamano_valor": "900"}, "tamano_incompleto"),
        ({"tamano_unidad": "ml"}, "tamano_incompleto"),
        ({"tamano_valor": "abc", "tamano_unidad": "ml"}, "tamano_no_numerico"),
        ({"tamano_valor": "-1", "tamano_unidad": "ml"}, "tamano_no_positivo"),
        ({"tamano_valor": "1", "tamano_unidad": "lt"}, "unidad_invalida"),
        ({"pack_cantidad": "1"}, "pack_invalido"),
        ({"pack_cantidad": "x"}, "pack_invalido"),
    ],
)
def test_motivos_de_fila_invalida(cambios, motivo):
    with pytest.raises(FilaInvalida) as e:
        fila_a_producto(fila(**cambios))
    assert e.value.motivo == motivo


def test_producto_a_fila_y_vuelta():
    p = Producto(
        ean=EAN,
        nombre='Leche, "entera"\ncon salto',
        marca="La Serenísima",
        tamano_valor=Decimal("1.50"),
        tamano_unidad="l",
        pack_cantidad=None,
        presentacion="sachet",
    )
    f = producto_a_fila(p, "off", "ojo")
    assert f["tamano_valor"] == "1.5" and f["fuente_origen"] == "off" and f["pack_cantidad"] == ""
    assert fila_a_producto(f).nombre == p.nombre


def test_escribir_y_leer_conserva_filas_y_hash(tmp_path):
    filas = [fila(ean="7790070411112", nombre='Leche, "entera"\ncon salto'), fila(nombre="B ñ")]
    ruta = tmp_path / "c.csv"
    sha = escribir(ruta, filas, {"generado": "hoy", "normalizador": "1"})
    lectura = leer(ruta)
    assert lectura.sha256 == sha == lectura.cabecera["contenido_sha256"]
    assert lectura.cabecera["formato"] == FORMATO and lectura.cabecera["normalizador"] == "1"
    assert [f for _, f in lectura.filas] == filas


def test_el_hash_no_depende_de_la_cabecera_ni_del_orden(tmp_path):
    a, b = fila(ean="7790070411112"), fila(ean="7790070411129", nombre="Otra cosa")
    s1 = escribir(tmp_path / "1.csv", [a, b], {"generado": "lunes"})
    s2 = escribir(tmp_path / "2.csv", [b, a], {"generado": "martes", "fuentes": "x"})
    assert s1 == s2
    assert [f["ean"] for _, f in leer(tmp_path / "2.csv").filas] == sorted([a["ean"], b["ean"]])


def test_gz_bom_y_crlf(tmp_path):
    ruta = tmp_path / "c.csv"
    sha = escribir(ruta, [fila()], {})
    texto = ruta.read_bytes().decode()
    crudo = ("﻿" + texto.replace("\n", "\r\n")).encode()
    gz = tmp_path / "c.csv.gz"
    gz.write_bytes(gzip.compress(crudo))
    assert leer(gz).sha256 == sha  # el hash es del contenido, no de cómo viajó


def test_editado_a_mano_se_nota(tmp_path):
    ruta = tmp_path / "c.csv"
    escribir(ruta, [fila()], {})
    ruta.write_text(ruta.read_text().replace("Cocinero", "Otra"), encoding="utf-8")
    lectura = leer(ruta)
    assert lectura.sha256 != lectura.cabecera["contenido_sha256"]


def test_numero_de_linea_con_campos_multilinea(tmp_path):
    ruta = tmp_path / "c.csv"
    escribir(ruta, [fila(nombre="uno\ndos"), fila(ean="7790070411129")], {})
    lineas = [n for n, _ in leer(ruta).filas]
    assert lineas[1] > lineas[0] + 1


def test_archivo_que_no_es_curado(tmp_path):
    ruta = tmp_path / "x.csv"
    ruta.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(FormatoInvalido):
        leer(ruta)
    ruta.write_text("# formato: otro_v9\nean,nombre\n", encoding="utf-8")
    with pytest.raises(FormatoInvalido):
        leer(ruta)


# --- v2: metadatos del tratamiento (docs/09) ---------------------------------------------


def fila_v2(**kw):
    base = dict.fromkeys(COLUMNAS_V2, "")
    base.update(ean="7790001234567", nombre="Aceite Girasol", **kw)
    return base


def test_v2_ida_y_vuelta_conserva_los_metadatos(tmp_path):
    ruta = tmp_path / "a.csv.gz"
    fila = fila_v2(origen="manual", campos_bloqueados="marca|nombre", sugerencias_aprobadas="2")
    escribir(ruta, [fila], {}, formato=FORMATO_V2)
    lectura = leer(ruta)
    assert lectura.cabecera["formato"] == FORMATO_V2
    assert lectura.filas[0][1]["campos_bloqueados"] == "marca|nombre"
    assert list(lectura.filas[0][1]) == list(COLUMNAS_V2)


def test_v1_sigue_sin_columnas_de_metadatos(tmp_path):
    ruta = tmp_path / "a.csv"
    escribir(ruta, [fila_v2()], {})
    assert list(leer(ruta).filas[0][1]) == list(COLUMNAS)


def test_meta_de_fila_valida_y_ordena():
    m = meta_de_fila(
        fila_v2(
            origen="manual",
            campos_bloqueados="presentacion|nombre",
            calidad="90",
            calidad_motivos="a|b",
            cargado_a_mano="1",
            conflictos_resueltos="3",
        )
    )
    assert m.origen == "manual" and m.bloqueados == ("nombre", "presentacion")
    assert m.hay_trabajo_humano
    assert m.info["calidad_motivos"] == ["a", "b"]
    assert m.info["cargado_a_mano"] is True and m.info["conflictos_resueltos"] == 3


def test_meta_de_fila_v1_es_none():
    assert meta_de_fila({"ean": "1", "nombre": "x"}) is None


@pytest.mark.parametrize(
    "cambios,motivo",
    [
        ({"origen": "otro"}, "origen_invalido"),
        ({"campos_bloqueados": "nombre|precio"}, "bloqueo_invalido"),
        ({"sugerencias_aprobadas": "x"}, "meta_invalida"),
        ({"revisado": "si"}, "meta_invalida"),
        ({"calidad": "alta"}, "meta_invalida"),
    ],
)
def test_meta_invalida(cambios, motivo):
    with pytest.raises(FilaInvalida) as e:
        meta_de_fila(fila_v2(**cambios))
    assert e.value.motivo == motivo
