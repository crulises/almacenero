import gzip
import io
import zipfile

import pytest

from etl.comun.paquete import LEEME, PaqueteInvalido, contenido_csv, escribir_zip, leeme_de
from etl.curado.formato import FormatoInvalido, escribir, leer
from etl.tests.test_curado_formato import fila


def test_zip_lleva_el_csv_y_el_leeme(tmp_path):
    ruta = tmp_path / "x.zip"
    escribir_zip(ruta, "x.csv", b"a,b\n1,2\n", "hola")
    with zipfile.ZipFile(ruta) as z:
        assert z.namelist() == [LEEME, "x.csv"]
        assert z.read(LEEME) == b"hola"
    assert contenido_csv(ruta.read_bytes()) == b"a,b\n1,2\n"  # ignora el LEEME


def test_se_reconoce_por_el_contenido_no_por_la_extension():
    assert contenido_csv(gzip.compress(b"x")) == b"x"
    assert contenido_csv(b"x,y\n") == b"x,y\n"
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("cualquier-nombre.CSV", b"z")
    assert contenido_csv(z.getvalue()) == b"z"


def test_zip_sin_csv_o_con_varios_o_roto():
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("a.txt", b"x")
    with pytest.raises(PaqueteInvalido, match="ningún"):
        contenido_csv(z.getvalue())
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("a.csv", b"x")
        f.writestr("b.csv", b"y")
    with pytest.raises(PaqueteInvalido, match="2 archivos"):
        contenido_csv(z.getvalue())
    with pytest.raises(PaqueteInvalido, match="roto"):
        contenido_csv(b"PK\x03\x04basura")
    with pytest.raises(PaqueteInvalido, match="roto"):
        contenido_csv(b"\x1f\x8bbasura")


def test_leeme_lleva_el_hash_y_las_secciones():
    texto = leeme_de("Titulo", [("Seccion", "cuerpo")])("abc123")
    assert "Titulo" in texto and "abc123" in texto and "Seccion\n-------\ncuerpo" in texto


def test_el_formato_curado_se_escribe_y_se_lee_en_zip(tmp_path):
    ruta = tmp_path / "c.zip"
    sha = escribir(ruta, [fila()], {"generado": "hoy"}, leeme=lambda s: f"sha {s}")
    with zipfile.ZipFile(ruta) as z:
        assert z.namelist() == [LEEME, "c.csv"]
        assert sha in z.read(LEEME).decode()
    lectura = leer(ruta)
    assert lectura.sha256 == sha  # el hash es del contenido: igual que en .csv o .gz
    assert len(lectura.filas) == 1
    # el mismo contenido en .csv y en .gz da el mismo hash
    assert leer_hash(tmp_path / "c.csv") == leer_hash(tmp_path / "c.csv.gz") == sha


def leer_hash(ruta):
    escribir(ruta, [fila()], {"generado": "hoy"})
    return leer(ruta).sha256


def test_zip_roto_en_el_formato_curado(tmp_path):
    ruta = tmp_path / "roto.zip"
    ruta.write_bytes(b"PK\x03\x04nada")
    with pytest.raises(FormatoInvalido, match="roto"):
        leer(ruta)
