import pytest

from etl.comun.rutas import NombreInvalido, ruta_de_salida, validar_nombre
from etl.registro import Definicion, Param, ParametroInvalido, validar


@pytest.mark.parametrize("n", ["a.csv", "catalogo-2026_11.csv.gz", "X1.csv"])
def test_nombres_validos(n):
    assert validar_nombre(n) == n


@pytest.mark.parametrize(
    "n", ["", "../a.csv", "/tmp/a.csv", "dir/a.csv", "a..b.csv", "a.txt", ".oculto.csv", "a b.csv"]
)
def test_nombres_invalidos(n):
    with pytest.raises(NombreInvalido):
        validar_nombre(n)


def test_ruta_cuelga_de_la_carpeta_base(tmp_path, monkeypatch):
    monkeypatch.setenv("ETL_EXPORT_DIR", str(tmp_path / "salidas"))
    r = ruta_de_salida("a.csv.gz")
    assert r == tmp_path / "salidas" / "a.csv.gz"
    assert r.parent.is_dir()


def test_param_nombre_archivo_valida_en_el_formulario():
    d = Definicion("x", "X", "", "local", (Param("salida", "nombre_archivo", True),), None)
    assert validar(d, {"salida": " a.csv "}) == {"salida": "a.csv"}
    with pytest.raises(ParametroInvalido):
        validar(d, {"salida": "../a.csv"})
