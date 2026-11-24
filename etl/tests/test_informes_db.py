"""Informes de calidad y renormalización: explican qué se aplicó (Postgres real, EAN 79999…)."""

import asyncio

from etl.calidad import medir
from etl.renormalizar import renormalizar
from etl.tests.test_off_db import db, ean, limpio, producto  # noqa: F401


def cargar_crudos():
    filas = [
        (ean(1), "ACEITE GIRASOL COCINERO 900 CC", "COCINERO"),
        (ean(2), "Limpiador p/ pisos 900 ml", "Mr Musculo"),
        (ean(3), "Xy", None),  # tan incompleto que se descarta
        (ean(4), "Aceite de Girasol", "Cocinero"),
    ]

    async def ins(c):
        for e, n, m in filas:
            await c.execute(
                "insert into productos_canonicos (ean, nombre, marca, origen)"
                " values ($1, $2, $3, 'sepa')",
                e,
                n,
                m,
            )

    db(ins)


def test_medir_explica_como_leerlo_y_que_reglas_aplica():
    cargar_crudos()
    texto = asyncio.run(medir(0, None, prefijo_ean="79999"))
    assert "Cómo leerlo" in texto and "Productos: 4" in texto
    assert "Productos que el normalizador cambiaría hoy: 2" in texto
    assert "Capitalización: 1 productos" in texto
    assert "abreviaturas más usadas: p/ (1)" in texto
    assert "no tiene tamaño" in texto  # el motivo, explicado
    assert "Reglas que aplica el normalizador, en orden" in texto and "Limpieza de texto" in texto
    assert "Ejemplos: no pediste ninguno" in texto


def test_los_parametros_de_medir_cambian_los_ejemplos():
    cargar_crudos()
    descartados = asyncio.run(medir(5, "descartado", prefijo_ean="79999"))
    lista = descartados.split("Ejemplos al azar")[1].split("Reglas que aplica")[0]
    assert "'Xy'" in lista and "'ACEITE GIRASOL" not in lista
    assert "(1 de 1 que cumplen, estado descartado)" in descartados
    todos = asyncio.run(medir(10, None, prefijo_ean="79999"))
    assert "'Xy'" in todos and "'ACEITE GIRASOL COCINERO 900 CC'" in todos
    assert "el normalizador lo dejaría: 'Aceite Girasol'" in todos
    uno = asyncio.run(medir(1, None, prefijo_ean="79999"))
    assert uno.count("; motivos:") == 1


def test_renormalizar_dice_que_transformaciones_aplico_y_cuantos_por_campo():
    cargar_crudos()
    texto = asyncio.run(renormalizar(False, prefijo_ean="79999"))
    assert "Cómo leerlo" in texto and "simulacro" in texto
    assert "Transformaciones aplicadas (2 productos afectados de 4)" in texto
    assert "Marca sacada del nombre" in texto and "Tamaño sacado del nombre" in texto
    assert "ej.: 'ACEITE GIRASOL COCINERO 900 CC' → 'Aceite Girasol'" in texto
    assert "Campos que cambian" in texto and "nombre: 2" in texto
    assert "Reglas que aplica el normalizador" in texto
    assert producto(ean(1))["nombre"] == "ACEITE GIRASOL COCINERO 900 CC"  # simulacro: no escribió


def test_renormalizar_sin_nada_que_hacer_lo_dice():
    async def ins(c):
        await c.execute(
            "insert into productos_canonicos (ean, nombre, marca, origen) values ($1,$2,$3,'sepa')",
            ean(4),
            "Aceite de Girasol",
            "Cocinero",
        )

    db(ins)
    asyncio.run(renormalizar(True, prefijo_ean="79999"))  # primera pasada: puntaje y estado
    texto = asyncio.run(renormalizar(False, prefijo_ean="79999"))
    assert "ya está normalizado" in texto and "Cambiarían: 0" in texto
