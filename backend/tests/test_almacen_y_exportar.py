"""Almacén de exportaciones y ETL `eventos_exportar` (docs/04 §11.4).

El mismo conjunto de pruebas corre contra **tres almacenes**: disco, el Storage S3 local de Supabase
(el de `make up`) y un S3 alternativo, SeaweedFS (`make s3-alt-up`, perfil opcional). Los dos S3
se saltean con un aviso si no están disponibles, para que el resto no dependa de ellos. Postgres es el real."""

import asyncio
import io
import json
import os
import shutil
import socket
import subprocess
import uuid
import zipfile
from datetime import datetime, timezone

import asyncpg
import pytest
from etl.comun import almacen as alm
from etl.eventos_exportar import exportar

from app.config import get_settings
from tests.db import sql

TIPO = "test.exportar"
BUCKET = "exportaciones-test"


def _supabase_s3() -> dict | None:
    """Las claves del S3 local: de EXPORT_S3_* si están, o de `supabase status`."""
    env = {k: os.environ.get(f"EXPORT_S3_{k}") for k in ("ENDPOINT", "KEY", "SECRET", "REGION")}
    if env["ENDPOINT"] and env["KEY"] and env["SECRET"] and "8333" not in env["ENDPOINT"]:
        return {**env, "REGION": env["REGION"] or "local"}
    if not shutil.which("supabase"):
        return None
    try:
        st = json.loads(
            subprocess.run(
                ["supabase", "status", "-o", "json"], capture_output=True, text=True, timeout=30
            ).stdout
        )
        return {
            "ENDPOINT": st["STORAGE_S3_URL"],
            "KEY": st["S3_PROTOCOL_ACCESS_KEY_ID"],
            "SECRET": st["S3_PROTOCOL_ACCESS_KEY_SECRET"],
            "REGION": st["S3_PROTOCOL_REGION"],
        }
    except Exception:  # noqa: BLE001
        return None


def _alternativo() -> dict | None:
    try:
        socket.create_connection(("127.0.0.1", 8333), timeout=1).close()
    except OSError:
        return None
    return {
        "ENDPOINT": "http://127.0.0.1:8333",
        "KEY": "almacenero",
        "SECRET": "almacenero-dev-secreto",
        "REGION": "us-east-1",
    }


@pytest.fixture(params=["disco", "supabase", "alternativo"])
def almacen(request, tmp_path):
    if request.param == "disco":
        yield alm.AlmacenDisco(tmp_path / "exports")
        return
    cfg = _supabase_s3() if request.param == "supabase" else _alternativo()
    if cfg is None:
        pytest.skip(f"{request.param}: no disponible (make up / make s3-alt-up)")
    a = alm.AlmacenS3(cfg["ENDPOINT"], BUCKET, cfg["KEY"], cfg["SECRET"], cfg["REGION"])
    a.asegurar()
    yield a
    for o in a.listar():
        a.borrar(o.clave)


class _Ctx:
    ejecucion_id = None
    filas = None

    def log(self, texto: str) -> None:
        pass


@pytest.fixture(autouse=True)
def _limpiar():
    sql(f"delete from eventos where tipo like '{TIPO}%'")
    sql(f"delete from eventos_exportaciones where tipo like '{TIPO}%'")
    yield
    sql(f"delete from eventos where tipo like '{TIPO}%'")
    sql(f"delete from eventos_exportaciones where tipo like '{TIPO}%'")


def _correr(coro):
    return asyncio.run(coro)


def _consulta(query: str, *args):
    async def run():
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            return await conn.fetch(query, *args)
        finally:
            await conn.close()

    return _correr(run())


def _eventos(n: int, tipo: str = TIPO, dia: str = "2026-11-20") -> list[int]:
    for i in range(n):
        sql(
            "insert into eventos (tipo, ocurrio_en, datos) values ($1, $2, $3::jsonb)",
            tipo,
            datetime.fromisoformat(f"{dia}T12:00:{i % 60:02d}+00:00"),
            json.dumps({"i": i, "ñ": "ü"}),
        )
    return [r["id"] for r in _consulta("select id from eventos where tipo = $1 order by id", tipo)]


def _quedan(tipo: str = TIPO) -> int:
    return _consulta("select count(*) as n from eventos where tipo = $1", tipo)[0]["n"]


# ------------------------------------------------------------ el almacén
def test_contrato_del_almacen(almacen):
    almacen.asegurar()
    almacen.guardar("pruebas/uno.bin", b"\x00\x01hola")
    assert almacen.leer("pruebas/uno.bin") == b"\x00\x01hola"
    almacen.guardar("pruebas/uno.bin", b"otro")  # reemplaza
    assert almacen.leer("pruebas/uno.bin") == b"otro"
    almacen.guardar("pruebas/dos.bin", b"2")
    assert sorted(o.clave for o in almacen.listar("pruebas/")) == [
        "pruebas/dos.bin",
        "pruebas/uno.bin",
    ]
    assert {o.clave: o.tamano for o in almacen.listar("pruebas/")}["pruebas/uno.bin"] == 4
    almacen.borrar("pruebas/uno.bin")
    almacen.borrar("pruebas/dos.bin")
    almacen.borrar("pruebas/no-existia.bin")  # borrar lo que no está no falla
    assert almacen.listar("pruebas/") == []
    with pytest.raises(alm.AlmacenError):
        almacen.leer("pruebas/uno.bin")


def test_probar_deja_el_almacen_como_estaba(almacen):
    r = alm.probar(almacen)
    assert r["almacen"] == almacen.nombre and r["bytes"] > 0
    assert almacen.listar("_prueba/") == []


@pytest.mark.parametrize(
    "clave", ["", "/abs", "../fuera", "a/../b", "a//b", "con espacio", "ñ.zip"]
)
def test_claves_invalidas(tmp_path, clave):
    with pytest.raises(alm.AlmacenError):
        alm.AlmacenDisco(tmp_path).guardar(clave, b"x")


def test_verificar_detecta_un_almacen_que_corrompe(tmp_path):
    class Corrupto(alm.AlmacenDisco):
        def leer(self, clave):
            return super().leer(clave)[:-1]  # pierde el último byte

    with pytest.raises(alm.AlmacenError, match="bytes"):
        alm.verificar(Corrupto(tmp_path), "a.bin", b"contenido")

    class Cambia(alm.AlmacenDisco):
        def leer(self, clave):
            return b"X" * len(super().leer(clave))

    with pytest.raises(alm.AlmacenError, match="sha256"):
        alm.verificar(Cambia(tmp_path), "b.bin", b"contenido")


def test_desde_entorno(tmp_path):
    assert alm.desde_entorno({"ETL_EXPORT_DIR": str(tmp_path)}).nombre == "disco"
    with pytest.raises(alm.AlmacenError, match="faltan"):
        alm.desde_entorno({"EXPORT_S3_ENDPOINT": "http://x"})
    s3 = alm.desde_entorno(
        {
            "EXPORT_S3_ENDPOINT": "http://x",
            "EXPORT_S3_BUCKET": "b",
            "EXPORT_S3_KEY": "k",
            "EXPORT_S3_SECRET": "s",
        }
    )
    assert s3.nombre == "s3" and s3.bucket == "b"


# ------------------------------------------------------- eventos_exportar
def _leer_zip(almacen, clave):
    z = zipfile.ZipFile(io.BytesIO(almacen.leer(clave)))
    assert sorted(z.namelist()) == ["LEEME.txt", "eventos.csv"]
    return z.read("eventos.csv").decode(), z.read("LEEME.txt").decode()


def test_exporta_verifica_y_borra_solo_lo_exportado(almacen):
    ids = _eventos(5)
    otros = _eventos(2, tipo=TIPO + ".otro")
    r = _correr(exportar({"tipo": TIPO, "borrar": True}, _Ctx(), almacen))
    assert (r["filas"], r["partes"], r["borradas"]) == (5, 1, 5)
    assert (r["id_desde"], r["id_hasta"]) == (ids[0], ids[-1])
    assert _quedan() == 0
    assert _quedan(TIPO + ".otro") == 2  # los de otro tipo no se tocan
    assert len(otros) == 2

    [fila] = _consulta("select * from eventos_exportaciones where tipo = $1", TIPO)
    assert (fila["filas"], fila["borradas"], fila["almacen"]) == (5, 5, almacen.nombre)
    assert (fila["id_desde"], fila["id_hasta"]) == (ids[0], ids[-1])
    datos = almacen.leer(fila["clave"])
    assert fila["tamano"] == len(datos) and fila["sha256"] == alm.sha256(datos)

    csv_texto, leeme = _leer_zip(almacen, fila["clave"])
    lineas = csv_texto.strip().split("\n")
    assert lineas[0] == "id,tipo,ocurrio_en,usuario_id,entidad,entidad_ref,datos"
    assert len(lineas) == 6
    assert lineas[1].startswith(f"{ids[0]},{TIPO},2026-11-20T12:00:00.000Z,")
    assert '"ñ": "ü"' in lineas[1].replace('""', '"')  # utf-8 sin escapar
    assert "ANÁLISIS INTERNO" in leeme and "ids de usuario" in leeme


def test_sin_borrar_exporta_y_deja_todo(almacen):
    _eventos(3)
    r = _correr(exportar({"tipo": TIPO}, _Ctx(), almacen))
    assert (r["filas"], r["borradas"]) == (3, 0)
    assert _quedan() == 3
    [fila] = _consulta("select borradas from eventos_exportaciones where tipo = $1", TIPO)
    assert fila["borradas"] == 0


def test_se_parte_en_varios_zip_con_su_rango_de_ids(almacen):
    ids = _eventos(5)
    r = _correr(exportar({"tipo": TIPO, "borrar": True, "filas_por_archivo": 2}, _Ctx(), almacen))
    assert (r["filas"], r["partes"], r["borradas"]) == (5, 3, 5)
    filas = _consulta(
        "select id_desde, id_hasta, filas from eventos_exportaciones "
        "where tipo = $1 order by id_desde",
        TIPO,
    )
    assert [(f["id_desde"], f["id_hasta"], f["filas"]) for f in filas] == [
        (ids[0], ids[1], 2),
        (ids[2], ids[3], 2),
        (ids[4], ids[4], 1),
    ]
    assert _quedan() == 0


def test_la_cantidad_por_archivo_sale_de_la_config(almacen, config_temporal):
    _eventos(4)
    config_temporal("eventos_export_filas_por_archivo", "3")
    r = _correr(exportar({"tipo": TIPO}, _Ctx(), almacen))
    assert r["partes"] == 2


def test_hasta_exporta_solo_hasta_el_fin_de_ese_dia_utc(almacen):
    _eventos(2, dia="2026-11-19")
    _eventos(3, dia="2026-11-21")
    r = _correr(exportar({"tipo": TIPO, "hasta": "2026-11-19", "borrar": True}, _Ctx(), almacen))
    assert (r["filas"], r["borradas"]) == (2, 2)
    assert _quedan() == 3


def test_sin_eventos_no_hay_archivo(almacen):
    r = _correr(exportar({"tipo": TIPO, "borrar": True}, _Ctx(), almacen))
    assert r == {"filas": 0, "partes": 0, "borradas": 0}
    assert almacen.listar("eventos/") == []


def test_si_la_verificacion_falla_no_se_borra_nada(tmp_path):
    class Corrupto(alm.AlmacenDisco):
        def leer(self, clave):
            return super().leer(clave)[:-1]

    _eventos(4)
    with pytest.raises(alm.AlmacenError):
        _correr(exportar({"tipo": TIPO, "borrar": True}, _Ctx(), Corrupto(tmp_path)))
    assert _quedan() == 4  # los eventos siguen ahí
    assert _consulta("select 1 from eventos_exportaciones where tipo = $1", TIPO) == []


def test_si_falla_la_segunda_parte_no_se_borra_ni_la_primera(tmp_path):
    class FallaLaSegunda(alm.AlmacenDisco):
        n = 0

        def guardar(self, clave, datos):
            FallaLaSegunda.n += 1
            if FallaLaSegunda.n == 2:
                raise alm.AlmacenError("se cayó el almacén")
            super().guardar(clave, datos)

    _eventos(4)
    with pytest.raises(alm.AlmacenError):
        _correr(
            exportar(
                {"tipo": TIPO, "borrar": True, "filas_por_archivo": 2},
                _Ctx(),
                FallaLaSegunda(tmp_path),
            )
        )
    assert _quedan() == 4
    assert _consulta("select 1 from eventos_exportaciones where tipo = $1", TIPO) == []


def test_un_evento_que_aparece_durante_la_exportacion_no_se_pierde(tmp_path):
    """El borrado es por los ids exportados, no por «todo lo anterior a N»: un evento que se
    confirma mientras se exporta (aunque tenga un id menor) queda en la base."""
    _eventos(3)

    class ConEventoTardio(alm.AlmacenDisco):
        def guardar(self, clave, datos):
            super().guardar(clave, datos)
            sql(
                "insert into eventos (tipo, datos) values ($1, '{}'::jsonb)",
                TIPO,
            )  # llega mientras se sube el archivo

    r = _correr(exportar({"tipo": TIPO, "borrar": True}, _Ctx(), ConEventoTardio(tmp_path)))
    assert (r["filas"], r["borradas"]) == (3, 3)
    assert _quedan() == 1


def test_el_zip_es_determinista_para_las_mismas_filas():
    from etl.eventos_exportar import armar_zip

    filas = [
        {
            "id": 1,
            "tipo": "a.b",
            "ocurrio_en": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "usuario_id": None,
            "entidad": None,
            "entidad_ref": None,
            "datos": '{"x": 1}',
        }
    ]
    a = armar_zip(filas, "k", 1, 1, None, None)
    z1 = zipfile.ZipFile(io.BytesIO(a)).read("eventos.csv")
    z2 = zipfile.ZipFile(io.BytesIO(armar_zip(filas, "k", 1, 1, None, None))).read("eventos.csv")
    assert z1 == z2


def test_la_definicion_esta_registrada():
    from etl.registro import obtener, validar

    d = obtener("eventos_exportar")
    assert d is not None and d.ejecutor == "web"
    assert validar(d, {"tipo": "producto.escaneado", "hasta": "2026-11-20", "borrar": "true"}) == {
        "tipo": "producto.escaneado",
        "hasta": "2026-11-20",
        "borrar": True,
    }
    assert validar(d, {}) == {"borrar": False}
    assert uuid.UUID(str(uuid.uuid4()))  # (uuid se usa para claves de prueba en otros tests)
