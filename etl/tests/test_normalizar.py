"""Casos reales del Doc 7 §8 como fixtures del normalizador (función pura, sin base)."""

from decimal import Decimal

import pytest

from etl.comun.normalizar import (
    COMPLETO,
    DESCARTADO,
    DUDOSO,
    NORMALIZADOR_VERSION,
    PARCIAL,
    Entrada,
    normalizar,
)

D = Decimal


@pytest.mark.parametrize(
    "entrada,nombre,marca,tamano,estado",
    [
        # Cebila: la marca viene como razón social; el tamaño del campo (3 l) se conserva.
        (
            Entrada("Aceite Cebila Oliva pet 3000 cc", "Agro Aceitunera S.a.", (D(3), "l")),
            "Aceite Oliva",
            "Cebila",
            (D(3), "l"),
            COMPLETO,
        ),
        # Sin tamaño en ningún lado: no se inventa.
        (
            Entrada("Aceite Chef Oliva Extra Virgen"),
            "Aceite Oliva Extra Virgen",
            "Chef",
            None,
            PARCIAL,
        ),
        # MAYÚSCULAS + abreviatura + marca truncada + tamaño pegado.
        (
            Entrada("ACEITE CANUELAS OLIVA CLAS.PVC 500ml.", "Aceite Canue"),
            "Aceite Oliva Clásico",
            "Cañuelas",
            (D(500), "ml"),
            COMPLETO,
        ),
        # Solo «Aceite»: demasiado incompleto.
        (Entrada("Aceite"), "Aceite", None, None, DESCARTADO),
        # Coreano completo (marca no latina): correcto, se deja tal cual.
        (Entrada("시원한 메밀소바", "농심"), "시원한 메밀소바", "농심", None, PARCIAL),
        # Coreano solo nombre: incompleto.
        (Entrada("막국슨"), "막국슨", None, None, DESCARTADO),
        # Pack 24x275ml con código de ERP delante: tamaño TOTAL y pack.
        (
            Entrada("0000018353 Gin Com Tonica Seager S 24x275ml"),
            "Gin Com Tonica",
            "Seager's",
            (D("6.6"), "l"),
            COMPLETO,
        ),
        # Nombre solo números / fecha y hora de vencimiento: inservible.
        (Entrada("0238321840", "a|x"), "0238321840", None, None, DESCARTADO),
        (Entrada("06:39 VENC:27/12/24"), "06:39 VENC:27/12/24", None, None, DESCARTADO),
        # Lysoform: marca truncada corregida; nombre abreviado queda `parcial`.
        (
            Entrada("Desinfect Amb Origin", "LYSOF", (D(380), "ml")),
            "Desinfect Amb Origin",
            "Lysoform",
            (D(380), "ml"),
            PARCIAL,
        ),
    ],
)
def test_casos_reales(entrada, nombre, marca, tamano, estado):
    s = normalizar(entrada)
    assert (s.nombre, s.marca, s.tamano, s.estado) == (nombre, marca, tamano, estado)


def test_cebila_fabricante_y_presentacion():
    s = normalizar(Entrada("Aceite Cebila Oliva pet 3000 cc", "Agro Aceitunera S.a.", (D(3), "l")))
    assert s.fabricante == "Agro Aceitunera S.a"
    assert s.presentacion == "pet"
    assert "fabricante_como_marca" in s.motivos


def test_pack_y_tamano_total():
    s = normalizar(Entrada("0000018353 Gin Com Tonica Seager S 24x275ml"))
    assert s.pack_cantidad == 24


def test_lysoform_abreviado_y_marca():
    s = normalizar(Entrada("Desinfect Amb Origin", "LYSOF", (D(380), "ml")))
    assert "abreviado" in s.motivos


def test_sufijo_de_envase_sepa():
    s = normalizar(Entrada("gin MERLE 750ml BOT-750-ml."))
    assert s.tamano == (D(750), "ml")
    assert s.presentacion == "botella"
    assert "750" not in s.nombre and "BOT" not in s.nombre


def test_campo_inverosimil_gana_el_nombre():
    # SEPA: cantidad .25 + unidad «gr.» con el nombre diciendo 250 g.
    s = normalizar(Entrada("Dulce de Batata LA GIOCONDA 700g LAT-700-gr.", None, (D("0.2"), "g")))
    assert s.tamano == (D(700), "g")
    assert "tamano_campo_corregido" in s.motivos


def test_conflicto_de_tamano_se_marca_y_no_toca_el_nombre():
    s = normalizar(Entrada("Yerba Mate Taragui 500g", "Taragui", (D(1), "kg")))
    assert s.tamano == (D(1), "kg")
    assert s.estado == DUDOSO
    assert "tamano_en_conflicto" in s.motivos
    assert "500g" in s.nombre


def test_uno_uni_no_es_tamano():
    s = normalizar(Entrada("Cepillo Dental Gum Soft", "Gum", (D(1), "u")))
    assert s.tamano is None


def test_conteo_de_unidades_y_pack():
    s = normalizar(Entrada("Maquina De Afeitar Comfort 3 Hybrid Bic X 6 Uni", "Bic"))
    assert s.tamano == (D(6), "u")
    assert s.pack_cantidad == 6


def test_placeholders_de_marca():
    for basura in ("S/d", "sin Marca", "Generico", "."):
        assert normalizar(Entrada("Atizador Para Asador Cromado", basura)).marca is None


def test_variantes_de_marca_unifican():
    marcas = {
        normalizar(Entrada("Leche Entera 1 l", m)).marca for m in ("nestle", "NESTLÉ", "Nestlé.")
    }
    assert marcas == {"Nestlé"}


def test_mayusculas_mezcladas():
    assert normalizar(Entrada("Jugo LOS NARANJOS Pomelo 1 l")).nombre == "Jugo Los Naranjos Pomelo"


def test_ambiguas_no_se_expanden():
    s = normalizar(Entrada("Yog Nat Deslac C/pro", "Dahi"))
    assert "Deslac" in s.nombre  # no se inventa «deslactosado»


def test_version_y_no_agrega_palabras():
    s = normalizar(Entrada("ACEITE OLIVA NUCETE EXTRA VIRGEN BOT 250 CC", "Nucete"))
    assert s.version == NORMALIZADOR_VERSION
    assert set(s.nombre.lower().split()) <= set("aceite oliva nucete extra virgen bot".split())


@pytest.mark.parametrize(
    "entrada",
    [
        Entrada("ACEITE CANUELAS OLIVA CLAS.PVC 500ml.", "Aceite Canue"),
        Entrada("Aceite Cebila Oliva pet 3000 cc", "Agro Aceitunera S.a.", (D(3), "l")),
        Entrada("0000018353 Gin Com Tonica Seager S 24x275ml"),
        Entrada("CHOCOLATE PARA TAZA, LA ANONIMA, 100 gr", "La Anonima"),
        Entrada(
            "Salsa Siracha CUISINE & CO NBE MP 250gr BOT-250-gr.", "Cuisine & Co", (D("0.25"), "g")
        ),
    ],
)
def test_idempotente(entrada):
    """normalizar(salida) == salida: volver a correrlo no cambia nada."""
    s1 = normalizar(entrada)
    s2 = normalizar(Entrada(s1.nombre, s1.marca, s1.tamano))
    assert (s2.nombre, s2.marca, s2.tamano) == (s1.nombre, s1.marca, s1.tamano)


def test_error_de_coma_en_el_campo():
    # SEPA: «1.5» con unidad gramos, y el nombre dice 1.5 kg.
    s = normalizar(
        Entrada("Alimento Dog Chow Cachorros x1.5kg BSA-1500-gr.", "Dog Chow", (D("1.5"), "g"))
    )
    assert s.tamano == (D("1.5"), "kg")
    assert "tamano_campo_corregido" in s.motivos


def test_cm3_y_unidades_de_sepa():
    s = normalizar(Entrada("Pomada Crema Negra, Wassington, 60 cm3", "Wassington"))
    assert s.tamano == (D(60), "ml")
    s = normalizar(Entrada("Huevos Blancos Maxima x6ud", "Maxima"))
    assert s.tamano == (D(6), "u") and s.pack_cantidad == 6
    s = normalizar(Entrada("Vasos Jerico Rigolleau 6unx350cc", "Rigolleau"))
    assert s.tamano == (D("2.1"), "l") and s.pack_cantidad == 6


def test_marca_no_vacia_el_nombre():
    # La «marca» de SEPA trae la palabra del producto: el nombre no queda en una sola palabra.
    s = normalizar(Entrada("SUAVIZANTE VIVERE CELESTE 4lt.", "Suavizante Vivere"))
    assert s.nombre == "Suavizante Vivere Celeste"


def test_envase_suelto_solo_con_tamano():
    assert "Pvc" in normalizar(Entrada("Alfombra Pvc Premium", "Premium")).nombre
