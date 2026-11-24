"""El normalizador registra QUÉ reglas aplicó (Doc 7 §4), y cada una se puede explicar."""

import pytest

from etl.comun.normalizar import Entrada, normalizar
from etl.comun.reglas_texto import MOTIVOS, TRANSFORMACIONES, base, reglas_en_orden


def ids(entrada: Entrada) -> set[str]:
    return set(normalizar(entrada).transformaciones)


def test_un_nombre_ya_limpio_no_aplica_nada():
    s = normalizar(Entrada("Aceite de Girasol", "Cocinero"))
    assert s.transformaciones == ()


def test_sepa_en_mayusculas_con_marca_y_tamano_en_el_nombre():
    t = ids(Entrada("ACEITE GIRASOL COCINERO 900 CC", "COCINERO"))
    assert {"tamano_del_nombre", "marca_fuera_del_nombre", "mayusculas"} <= t


def test_sufijo_de_envase_de_sepa():
    s = normalizar(Entrada("AGUA MINERAL SERRANA BOT-750-ml."))
    assert "sufijo_envase_sepa" in s.transformaciones and s.presentacion == "botella"


def test_marca_placeholder_y_marca_canonica():
    assert "marca_placeholder" in ids(Entrada("Fideos Tirabuzon", "S/d"))
    assert "marca_canonica" in ids(Entrada("Fideos Tirabuzon", "LUCCHETTI"))


def test_razon_social_pasa_a_fabricante():
    s = normalizar(Entrada("Galletitas Dulces", "Alimentos Ricos S.A."))
    assert "razon_social_a_fabricante" in s.transformaciones and s.fabricante


def test_marca_que_solo_estaba_en_el_nombre():
    assert "marca_desde_nombre" in ids(Entrada("Lavandina Ayudin 1 L"))


def test_abreviatura_expandida_dice_cual():
    t = ids(Entrada("Limpiador p/ pisos 900 ml", "Mr Musculo"))
    assert "abreviatura_expandida:p/" in t


def test_codigo_interno_y_limpieza():
    t = ids(Entrada("000123 Leche  Entera  1 L", "La Serenisima"))
    assert {"codigo_erp", "limpieza_texto"} <= t


def test_pack_detectado():
    assert "pack_detectado" in ids(Entrada("Gaseosa Cola 6 x 330 ml", "Coca Cola"))


@pytest.mark.parametrize(
    "e",
    [
        Entrada("ACEITE GIRASOL COCINERO 900 CC", "COCINERO"),
        Entrada("Limpiador p/ pisos 900 ml", "Mr Musculo"),
        Entrada("AGUA MINERAL SERRANA BOT-750-ml."),
        Entrada("Lavandina Ayudin 1 L"),
    ],
)
def test_normalizar_lo_normalizado_no_aplica_nada(e):
    s = normalizar(e)
    de_nuevo = normalizar(Entrada(s.nombre, s.marca, s.tamano, False, s.presentacion))
    assert de_nuevo.transformaciones == ()


def test_todo_id_que_se_emite_tiene_explicacion():
    casos = [
        Entrada("ACEITE GIRASOL COCINERO 900 CC", "COCINERO"),
        Entrada("AGUA MINERAL SERRANA BOT-750-ml.", "S/d"),
        Entrada("Galletitas Dulces", "Alimentos Ricos S.A."),
        Entrada("Lavandina Ayudin 1 L"),
        Entrada("000123 Leche  Entera  1 L", "La Serenisima"),
        Entrada("Gaseosa Cola 6 x 330 ml", "Coca Cola"),
        Entrada("Limpiador p/ pisos 900 ml", "Mr Musculo"),
    ]
    vistos = {t for e in casos for t in normalizar(e).transformaciones}
    assert vistos and all(base(t) in TRANSFORMACIONES for t in vistos)
    motivos = {m for e in casos for m in normalizar(e).motivos}
    assert motivos <= set(MOTIVOS)


def test_las_reglas_se_listan_en_orden_con_su_explicacion():
    texto = reglas_en_orden()
    assert texto.index("Limpieza de texto") < texto.index("Capitalización")
    assert "p/" in texto  # el ejemplo de las abreviaturas
    assert all(titulo in texto for titulo, *_ in TRANSFORMACIONES.values())
