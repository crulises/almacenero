"""Resumen legible de lo que hizo el normalizador (para el log de las ejecuciones de ETL)."""

from etl.comun.normalizar import Entrada, normalizar
from etl.comun.resumen import Trazas, explicar_motivos


def agregar(t: Trazas, nombre: str, marca: str | None = None) -> None:
    s = normalizar(Entrada(nombre, marca))
    t.agregar(s, nombre, s.nombre)


def test_cuenta_por_regla_con_ejemplo_y_porcentaje():
    t = Trazas()
    agregar(t, "ACEITE GIRASOL COCINERO 900 CC", "COCINERO")
    agregar(t, "LECHE ENTERA 1 L", "La Serenisima")
    agregar(t, "Aceite de Girasol", "Cocinero")  # ya limpio: no cuenta como afectado
    texto = t.texto(total=3)
    assert t.afectados == 2
    assert "Capitalización: 2 productos (66,7 %)" in texto
    assert "ej.: 'ACEITE GIRASOL COCINERO 900 CC' → '" in texto


def test_detalla_las_abreviaturas_mas_usadas():
    t = Trazas()
    for _ in range(3):
        agregar(t, "Limpiador p/ pisos 900 ml", "Mr Musculo")
    agregar(t, "Crema c/ aloe 200 ml", "Nivea")
    texto = t.texto(total=4)
    assert "p/ (3)" in texto and "c/ (1)" in texto


def test_sin_nada_que_transformar_lo_dice():
    t = Trazas()
    agregar(t, "Aceite de Girasol", "Cocinero")
    assert "ya está normalizado" in t.texto(total=1)


def test_explicar_motivos_en_lenguaje_llano():
    texto = explicar_motivos({"sin_tamano": 50, "abreviado": 5}, total=100)
    assert "no tiene tamaño" in texto and "50,0 %" in texto and "abreviatura ambigua" in texto
    assert texto.index("sin_tamano") < texto.index("abreviado")  # de más a menos
