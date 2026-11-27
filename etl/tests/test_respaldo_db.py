# ruff: noqa: E501
"""Respaldo y restauración (`etl/respaldo.py`). Restaurar BORRA datos, así que estos tests nunca
tocan la base de desarrollo: crean una base temporal (esquema clonado con pg_dump) y la borran."""

import asyncio
import os
import shutil
import subprocess
import uuid

import asyncpg
import pytest

from etl.comun.almacen import AlmacenDisco
from etl.comun.catalogo import database_url
from etl.respaldo import PALABRA, RespaldoError, crear, restaurar

pytestmark = pytest.mark.skipif(
    not (shutil.which("pg_dump") and shutil.which("psql")), reason="falta pg_dump/psql"
)


def _urls():
    base = database_url().split("?")[0]
    raiz = base.rsplit("/", 1)[0]
    return base, f"{raiz}/postgres", raiz


@pytest.fixture()
def base_temporal():
    origen, admin, raiz = _urls()
    nombre = f"almacenero_respaldo_{uuid.uuid4().hex[:8]}"
    url = f"{raiz}/{nombre}"
    subprocess.run(["psql", admin, "-q", "-c", f"create database {nombre}"], check=True)
    try:
        for ext in ("postgis", "pg_trgm", "unaccent"):
            subprocess.run(
                ["psql", url, "-q", "-c", f"create extension if not exists {ext}"],
                check=True,
            )
        esquema = subprocess.run(
            [
                "pg_dump",
                origen,
                "--schema-only",
                "--schema=public",
                "--no-owner",
                "--no-privileges",
                "--exclude-table=spatial_ref_sys",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        esquema = "\n".join(
            ln
            for ln in esquema.splitlines()
            if not ln.startswith(("SET transaction_timeout", "CREATE SCHEMA public;"))
        )
        subprocess.run(
            ["psql", url, "-q", "-v", "ON_ERROR_STOP=1", "-o", os.devnull],
            input=esquema,
            text=True,
            check=True,
        )
        yield url
    finally:
        subprocess.run(
            [
                "psql",
                admin,
                "-q",
                "-c",
                f"drop database if exists {nombre} with (force)",
            ]
        )


def correr(url, f):
    async def _():
        c = await asyncpg.connect(url)
        try:
            return await f(c)
        finally:
            await c.close()

    return asyncio.run(_())


async def _sembrar(c):
    await c.execute(
        "select set_config('app.rol_write','on',false), set_config('app.karma_write','on',false)"
    )
    # un respaldo viejo puede traer alias repetidos (el índice único es posterior): se simula
    await c.execute("drop index usuarios_alias_unico_idx")
    await c.execute(
        "insert into usuarios (id, auth_id, alias, karma, rol) values "
        "('00000000-0000-0000-0000-0000000000a1','00000000-0000-0000-0000-0000000000b1','Ana',3,'admin'),"
        "('00000000-0000-0000-0000-0000000000a2','00000000-0000-0000-0000-0000000000b2','Ana',0,'usuario')"
    )
    await c.execute(
        "insert into productos_canonicos (ean, nombre) values ('77900010','Yerba'), ('77900029','Fideos')"
    )
    await c.execute("insert into eventos (tipo) values ('app.abierta'), ('app.abierta')")
    await c.execute("update config set valor = '42' where clave = 'max_precios_por_hora'")


async def _estado(c):
    return (
        await c.fetchval("select count(*) from usuarios"),
        await c.fetchval("select count(*) from productos_canonicos"),
        await c.fetchval("select valor::text from config where clave='max_precios_por_hora'"),
    )


def test_ida_y_vuelta_reemplaza_los_datos(base_temporal, tmp_path):
    url, alm = base_temporal, AlmacenDisco(tmp_path)
    correr(url, _sembrar)
    antes = correr(url, _estado)
    res = asyncio.run(crear(url, nombre="t", con_eventos=True, almacen=alm, log=lambda *_: None))
    assert res.clave.startswith("respaldo/t-") and res.tablas["productos_canonicos"] == 2

    # se rompe la base después del respaldo
    async def estropear(c):
        await c.execute("delete from productos_canonicos")
        await c.execute("delete from eventos")
        await c.execute("delete from usuarios")
        await c.execute(
            "create unique index usuarios_alias_unico_idx on usuarios (lower(alias)) "
            "where alias !~* '^anon-'"
        )
        await c.execute("update config set valor = '1' where clave = 'max_precios_por_hora'")

    correr(url, estropear)
    archivo = f"almacen:{res.clave}"

    sim = asyncio.run(restaurar(archivo, url, almacen=alm, log=lambda *_: None))  # simulacro
    assert not sim.aplicado and sim.tablas["productos_canonicos"] == {
        "respaldo": 2,
        "ahora": 0,
    }
    assert correr(url, _estado)[1] == 0  # no escribió nada

    with pytest.raises(RespaldoError):  # sin la palabra de confirmación no se restaura
        asyncio.run(restaurar(archivo, url, aplicar=True, confirmacion="si", almacen=alm))

    ok = asyncio.run(
        restaurar(
            archivo,
            url,
            aplicar=True,
            confirmacion=PALABRA,
            almacen=alm,
            log=lambda *_: None,
        )
    )
    assert ok.aplicado and ok.seguridad
    assert correr(url, _estado) == antes  # 2 usuarios: el alias repetido se renombró para entrar
    # el alias repetido se renombró (índice único) y la seguridad quedó guardada y verificable
    assert (
        correr(
            url,
            lambda c: c.fetchval("select count(distinct lower(alias)) from usuarios"),
        )
        == 2
    )
    # la identidad (eventos.id) se cargó y la secuencia sigue sin chocar
    assert correr(url, lambda c: c.fetchval("select count(*) from eventos")) == 2
    assert (
        correr(url, lambda c: c.fetchval("insert into eventos (tipo) values ('x') returning id"))
        > 2
    )
    assert any(o.clave == ok.seguridad for o in alm.listar("respaldo/"))


def test_un_archivo_dañado_no_toca_nada(base_temporal, tmp_path):
    url, alm = base_temporal, AlmacenDisco(tmp_path)
    correr(url, _sembrar)
    res = asyncio.run(crear(url, almacen=alm, log=lambda *_: None))
    ruta = tmp_path / res.clave
    ruta.write_bytes(ruta.read_bytes()[:-40])  # truncado
    with pytest.raises(RespaldoError):
        asyncio.run(restaurar(str(ruta), url, aplicar=True, confirmacion=PALABRA, almacen=alm))
    assert correr(url, _estado)[1] == 2
