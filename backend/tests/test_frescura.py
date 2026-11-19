import pytest

from app.services.frescura import clasificar


@pytest.mark.parametrize(
    ("edad", "esperado"),
    [(0, "verde"), (7, "verde"), (8, "amarillo"), (21, "amarillo"), (22, "rojo"), (400, "rojo")],
)
def test_clasifica_por_antiguedad(edad, esperado):
    assert clasificar(edad, umbral_verde=7, umbral_amarillo=21) == esperado
