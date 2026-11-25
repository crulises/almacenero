"""`publicar_archivo`: el .zip de un export de intercambio también queda en el almacén."""

from pathlib import Path

from etl.comun.almacen import AlmacenDisco, publicar_archivo


def test_con_almacen_en_disco_no_duplica(tmp_path: Path):
    z = tmp_path / "x.zip"
    z.write_bytes(b"datos")
    msg = publicar_archivo(z, almacen=AlmacenDisco(tmp_path / "otro"))
    assert "disco" in msg and not (tmp_path / "otro").exists()


def test_sube_y_verifica_en_un_almacen_que_no_es_disco(tmp_path: Path):
    z = tmp_path / "x.zip"
    z.write_bytes(b"datos")
    destino = AlmacenDisco(tmp_path / "s3")
    destino.nombre = "s3"  # se comporta como un almacén remoto
    msg = publicar_archivo(z, almacen=destino)
    assert "intercambio/x.zip" in msg
    assert (tmp_path / "s3" / "intercambio" / "x.zip").read_bytes() == b"datos"
