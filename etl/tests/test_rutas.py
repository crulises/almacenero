import pytest

from etl.comun.rutas import NombreInvalido, ruta_de_salida, validar_nombre
from etl.registro import Definicion, Param, ParametroInvalido, validar


@pytest.mark.parametrize(
    "escrito, esperado",
    [
        ("catalogo", "catalogo"),
        ("catalogo-2026_11", "catalogo-2026_11"),
        ("v1.2", "v1.2"),
        # quien igual escribe una extensión de formato: se ignora
        ("a.csv", "a"),
        ("a.csv.gz", "a"),
        ("a.ZIP", "a"),
        ("  X1.zip  ", "X1"),
    ],
)
def test_nombres_validos(escrito, esperado):
    assert validar_nombre(escrito) == esperado


@pytest.mark.parametrize(
    "n", ["", "../a", "/tmp/a", "dir/a", "a..b", ".oculto", "a b", ".zip", "a.", "x" * 101]
)
def test_nombres_invalidos(n):
    with pytest.raises(NombreInvalido):
        validar_nombre(n)


def test_ruta_cuelga_de_la_carpeta_base_y_pone_la_extension(tmp_path, monkeypatch):
    monkeypatch.setenv("ETL_EXPORT_DIR", str(tmp_path / "salidas"))
    r = ruta_de_salida("a")
    assert r == tmp_path / "salidas" / "a.zip"
    assert r.parent.is_dir()
    assert ruta_de_salida("a.csv.gz") == r  # no hace falta saber de formatos


def test_param_nombre_archivo_valida_en_el_formulario():
    d = Definicion("x", "X", "", "local", (Param("salida", "nombre_archivo", True),), None)
    assert validar(d, {"salida": " a.csv "}) == {"salida": "a"}
    assert validar(d, {"salida": "mi-export"}) == {"salida": "mi-export"}
    with pytest.raises(ParametroInvalido):
        validar(d, {"salida": "../a"})
