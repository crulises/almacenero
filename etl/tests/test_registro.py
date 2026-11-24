"""Registro de ETL: definiciones con sus parámetros y validación del formulario."""

import pytest

from etl.registro import Definicion, Param, ParametroInvalido, describir, obtener, todas, validar

DEF = Definicion(
    clave="prueba",
    titulo="Prueba",
    descripcion="d",
    ejecutor="web",
    parametros=(
        Param("n", "entero", obligatorio=True, ayuda="cuántos"),
        Param("activo", "booleano", default=False),
        Param("modo", "opcion", opciones=("a", "b"), default="a"),
        Param("desde", "fecha"),
        Param("texto", "texto"),
    ),
    ejecutar=lambda p, ctx: None,
)


def test_aplica_defaults_y_convierte_tipos():
    assert validar(DEF, {"n": "5", "activo": "true", "desde": "2026-11-24"}) == {
        "n": 5,
        "activo": True,
        "modo": "a",
        "desde": "2026-11-24",
    }


@pytest.mark.parametrize(
    ("payload", "param"),
    [
        ({}, "n"),  # obligatorio
        ({"n": "abc"}, "n"),
        ({"n": True}, "n"),  # un booleano no es un entero
        ({"n": 1, "activo": "tal vez"}, "activo"),
        ({"n": 1, "modo": "c"}, "modo"),
        ({"n": 1, "desde": "mañana"}, "desde"),
        ({"n": 1, "texto": "x" * 501}, "texto"),
        ({"n": 1, "inventado": 1}, "inventado"),  # parámetro que no existe
    ],
)
def test_parametros_invalidos_dicen_cual(payload, param):
    with pytest.raises(ParametroInvalido) as e:
        validar(DEF, payload)
    assert e.value.nombre == param and e.value.mensaje


def test_el_registro_real_describe_sus_etl():
    claves = {d.clave for d in todas()}
    assert {
        "curado_importar",
        "catalogo_renormalizar",
        "catalogo_calidad",
        "off",
        "sepa",
        "sepa_locales",
        "osm",
        "curado_exportar",
    } <= claves
    for d in todas():
        assert d.ejecutor in ("web", "local")
        assert all(
            p.tipo
            in ("texto", "entero", "booleano", "opcion", "fecha", "archivo", "nombre_archivo")
            for p in d.parametros
        )
        assert all(p.ayuda for p in d.parametros), d.clave  # el panel muestra la ayuda
    assert obtener("curado_importar").ejecutor == "web"
    assert obtener("sepa").ejecutor == "local"
    assert obtener("no-existe") is None


def test_describir_es_json_para_el_panel():
    d = describir(obtener("curado_importar"))
    assert d["clave"] == "curado_importar" and d["ejecutor"] == "web"
    assert {"nombre", "tipo", "obligatorio", "ayuda", "default", "opciones"} <= set(
        d["parametros"][0]
    )
    assert "ejecutar" not in d


def test_probar_el_normalizador_explica_paso_a_paso():
    import asyncio

    class Ctx:
        def __init__(self):
            self.lineas = []

        def log(self, t):
            self.lineas.append(t)

    ctx = Ctx()
    rep = asyncio.run(
        obtener("normalizador_probar").ejecutar(
            {"nombre": "ACEITE GIRASOL COCINERO 900 CC", "marca": "COCINERO"}, ctx
        )
    )
    texto = "\n".join(ctx.lineas)
    assert rep["nombre"] == "Aceite Girasol" and rep["marca"] == "Cocinero"
    assert "Reglas que se aplicaron" in texto and "Capitalización" in texto
    assert "puntaje" in texto and "estado" in texto
