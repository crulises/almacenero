from app.services.karma import KARMA_POR_CARGA, karma_por_carga


def test_karma_por_defecto():
    assert karma_por_carga() == KARMA_POR_CARGA


def test_karma_configurable():
    assert karma_por_carga({"karma_por_carga": 5}) == 5


def test_karma_config_invalida_usa_default():
    assert karma_por_carga({"karma_por_carga": "x"}) == KARMA_POR_CARGA
