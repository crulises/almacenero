"""Cola de ETL (docs/04 §10-A): tomar, correr como subproceso, cancelar, recuperar. Postgres real."""

import asyncio
import hashlib
import json
import os
import sys
import time

import asyncpg
import pytest

from etl.comun.catalogo import database_url
from etl.ejecucion import ciclo, recuperar_huerfanas, tomar

os.environ["ETL_DEFINICIONES_EXTRA"] = "etl.tests.defs_prueba"  # lo heredan los subprocesos


def run(coro_fn):
    async def go():
        conn = await asyncpg.connect(database_url())
        try:
            return await coro_fn(conn)
        finally:
            await conn.close()

    return asyncio.run(go())


@pytest.fixture(autouse=True)
def limpio():
    async def borrar(c):
        await c.execute("delete from etl_ejecuciones where etl like 't\\_%'")
        await c.execute("delete from etl_archivos where nombre like 't-%'")

    run(borrar)
    yield
    run(borrar)


async def encolar(c, etl, ejecutor="local", parametros=None):
    return await c.fetchval(
        "insert into etl_ejecuciones (etl, ejecutor, parametros) values ($1,$2,$3::jsonb)"
        " returning id",
        etl,
        ejecutor,
        json.dumps(parametros or {}),
    )


async def ver(c, id_):
    return await c.fetchrow("select * from etl_ejecuciones where id = $1", id_)


def test_corre_el_etl_y_guarda_log_reporte_y_filas():
    async def t(c):
        id_ = await encolar(c, "t_eco", parametros={"n": 3})
        assert await ciclo(c, "local", max_s=60) is True
        e = await ver(c, id_)
        assert e["estado"] == "ok" and e["terminado_en"] and e["iniciado_en"] and e["latido_en"]
        assert json.loads(e["reporte"]) == {"n": 1} and e["filas"] == 7
        assert "hola desde el ETL" in e["log"] and "n=3" in e["log"]
        assert await ciclo(c, "local", max_s=60) is False  # cola vacía

    run(t)


def test_un_etl_que_rompe_queda_en_fallo_con_el_motivo():
    async def t(c):
        id_ = await encolar(c, "t_falla")
        await ciclo(c, "local", max_s=60)
        e = await ver(c, id_)
        assert e["estado"] == "fallo" and e["terminado_en"]
        assert "se rompió a propósito" in e["log"] and "antes de romper" in e["log"]

    run(t)


def test_etl_desconocido_falla_sin_trabarse():
    async def t(c):
        id_ = await encolar(c, "t_no_existe")
        await ciclo(c, "local", max_s=60)
        e = await ver(c, id_)
        assert e["estado"] == "fallo" and "t_no_existe" in e["log"]

    run(t)


def test_cada_ejecutor_toma_lo_suyo_y_de_a_uno():
    async def t(c):
        a = await encolar(c, "t_eco", "local")
        b = await encolar(c, "t_eco", "local")
        w = await encolar(c, "t_eco_web", "web")
        tomada = await tomar(c, "local")
        assert tomada["id"] == a and (await ver(c, a))["estado"] == "corriendo"
        assert await tomar(c, "local") is None  # ya hay una corriendo en ese ejecutor
        assert (await ver(c, b))["estado"] == "en_cola"
        assert (await ver(c, w))["estado"] == "en_cola"  # el `web` no lo toca el `local`

    run(t)


def test_cancelar_una_corriendo_corta_el_subproceso():
    async def t():
        c = await asyncpg.connect(database_url())
        c2 = await asyncpg.connect(database_url())
        try:
            id_ = await encolar(c, "t_dormir")
            tarea = asyncio.create_task(ciclo(c2, "local", max_s=60, latido_s=0.3, gracia_s=5))
            for _ in range(100):
                await asyncio.sleep(0.2)
                if (await ver(c, id_))["estado"] == "corriendo":
                    break
            await c.execute("update etl_ejecuciones set cancelar = true where id = $1", id_)
            t0 = time.monotonic()
            await tarea
            e = await ver(c, id_)
            assert e["estado"] == "cancelada" and e["terminado_en"]
            assert time.monotonic() - t0 < 15
        finally:
            await c.close()
            await c2.close()

    asyncio.run(t())


def test_pasarse_de_tiempo_es_fallo():
    async def t(c):
        id_ = await encolar(c, "t_dormir")
        await ciclo(c, "local", max_s=1, latido_s=0.3, gracia_s=2)
        e = await ver(c, id_)
        assert e["estado"] == "fallo" and "tiempo" in e["log"].lower()

    run(t)


def test_sin_latido_se_marca_fallo():
    async def t(c):
        id_ = await encolar(c, "t_eco")
        await c.execute(
            "update etl_ejecuciones set estado='corriendo', iniciado_en = now() - interval '9 min',"
            " latido_en = now() - interval '5 min' where id = $1",
            id_,
        )
        assert await recuperar_huerfanas(c, "local", segundos=120) == 1
        e = await ver(c, id_)
        assert e["estado"] == "fallo" and "latido" in e["log"]
        assert await tomar(c, "local") is None

    run(t)


async def subir(c, nombre, texto):
    b = texto.encode()
    return await c.fetchval(
        "insert into etl_archivos (nombre, sha256, tamano, contenido) values ($1,$2,$3,$4)"
        " returning id",
        nombre,
        hashlib.sha256(b).hexdigest(),
        len(b),
        b,
    )


def meta(id_, nombre):
    return {"id": str(id_), "nombre": nombre}


def test_el_archivo_llega_al_etl_y_se_borra_solo_al_aplicar():
    async def t(c):
        a = await subir(c, "t-datos.csv", "contenido uno")
        sim = await encolar(c, "t_archivo", parametros={"archivo": meta(a, "t-datos.csv")})
        await ciclo(c, "local", max_s=60)
        e = await ver(c, sim)
        assert e["estado"] == "ok" and "archivo t-datos.csv: contenido uno" in e["log"]
        assert (
            await c.fetchval("select count(*) from etl_archivos where id = $1", a) == 1
        )  # simulacro
        real = await encolar(
            c, "t_archivo", parametros={"archivo": meta(a, "t-datos.csv"), "aplicar": True}
        )
        await ciclo(c, "local", max_s=60)
        assert (await ver(c, real))["estado"] == "ok"
        assert await c.fetchval("select count(*) from etl_archivos where id = $1", a) == 0

    run(t)


def test_archivo_inexistente_explica_que_pasó():
    async def t(c):
        id_ = await encolar(
            c,
            "t_archivo",
            parametros={"archivo": meta("00000000-0000-0000-0000-000000000000", "x")},
        )
        await ciclo(c, "local", max_s=60)
        e = await ver(c, id_)
        assert e["estado"] == "fallo" and "ya no está" in e["log"]

    run(t)


def test_los_archivos_viejos_se_purgan():
    async def t(c):
        a = await subir(c, "t-viejo.csv", "x")
        await c.execute(
            "update etl_archivos set creado_en = now() - interval '25 h' where id=$1", a
        )
        await ciclo(c, "local", max_s=60)
        assert await c.fetchval("select count(*) from etl_archivos where id = $1", a) == 0

    run(t)


def test_python_es_el_mismo_del_test():
    assert sys.executable  # los subprocesos usan sys.executable
