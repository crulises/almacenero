"""Formato de intercambio v2 (docs/09): exportar desde la base con todos los metadatos del
tratamiento y volver a importarlo sin perder nada. Contra Postgres local real."""

import asyncio
import json

import pytest

from etl.curado.exportar_base import exportar_base
from etl.curado.formato import FORMATO_V2, leer
from etl.curado.importar import importar
from etl.tests.test_off_db import db, ean, limpio, producto  # noqa: F401


def _limpiar_auditoria(c):
    return c.execute(
        "delete from auditoria_admin where entidad = 'producto' and entidad_id in"
        " (select id::text from productos_canonicos where ean like '79999%')"
    )


@pytest.fixture(autouse=True)
def auditoria_limpia():
    db(_limpiar_auditoria)
    db(lambda c: c.execute("delete from catalogo_lotes where nombre_archivo like 'test-%'"))
    yield
    db(_limpiar_auditoria)
    db(lambda c: c.execute("delete from catalogo_lotes where nombre_archivo like 'test-%'"))


@pytest.fixture
def usuario():
    u = db(lambda c: c.fetchval("select id from usuarios limit 1"))
    if u is None:
        pytest.skip("hace falta algún usuario en la base local")
    return u


async def _sembrar(c, usuario):
    """Tres productos con historias distintas."""
    a, b, d = ean(1), ean(2), ean(3)
    async with c.transaction():
        await c.execute("select set_config('app.catalogo_write', 'on', true)")
        # A: cargado a mano, con campos bloqueados, una corrección del admin y una sugerencia
        await c.execute(
            "insert into productos_canonicos (ean, nombre, marca, tamano_valor, tamano_unidad,"
            " origen, campos_bloqueados) values ($1, 'Aceite de Girasol', 'Cocinero', 900, 'ml',"
            " 'manual', array['nombre','tamano'])",
            a,
        )
        pid = await c.fetchval("select id from productos_canonicos where ean = $1", a)
        await c.execute(
            "insert into auditoria_admin (usuario_id, accion, entidad, entidad_id)"
            " values ($1, 'producto.corregir', 'producto', $2)",
            usuario,
            str(pid),
        )
        await c.execute(
            "insert into sugerencias_catalogo (producto_id, ean, usuario_id, cambios, estado,"
            ' resuelto_por, resuelto_en) values ($1, $2, $3, \'{"marca":"Cocinero"}\'::jsonb,'
            " 'aprobada', $3, now())",
            pid,
            a,
            usuario,
        )
        # B: de SEPA, con un conflicto resuelto y otro pendiente
        await c.execute(
            "insert into productos_canonicos (ean, nombre, marca, origen)"
            " values ($1, 'Fideos Tirabuzón', 'Lucchetti', 'sepa')",
            b,
        )
        for estado in ("resuelto", "pendiente"):
            await c.execute(
                "insert into conflictos_catalogo (ean, campo, valor_a, fuente_a, valor_b,"
                " fuente_b, estado, resuelto_por, resuelto_en, elegido)"
                " select $1, 'marca', 'x' || $2::text, 'off', 'y', 'sepa', $2::text,"
                " case when $2::text = 'resuelto' then $3::uuid end,"
                " case when $2::text = 'resuelto' then now() end,"
                " case when $2::text = 'resuelto' then 'a' end",
                b,
                estado,
                usuario,
            )
        # D: de OFF, sin historia
        await c.execute(
            "insert into productos_canonicos (ean, nombre, origen, calidad, estado_calidad,"
            " normalizador_version) values ($1, 'Galletitas', 'off', 80, 'completo', 3)",
            d,
        )
    return a, b, d


def test_el_export_de_la_base_lleva_todos_los_metadatos(tmp_path, usuario):
    a, b, d = db(lambda c: _sembrar(c, usuario))
    ruta = tmp_path / "test-base.csv.gz"
    r = asyncio.run(exportar_base(ruta, prefijo_ean="79999"))
    assert r.filas == 3
    lectura = leer(ruta)
    assert lectura.cabecera["formato"] == FORMATO_V2
    f = {fila["ean"]: fila for _, fila in lectura.filas}
    assert f[a]["origen"] == "manual"
    assert f[a]["campos_bloqueados"] == "nombre|tamano"
    assert (f[a]["cargado_a_mano"], f[a]["revisado"]) == ("1", "1")
    assert f[a]["ediciones_admin"] == "1" and f[a]["sugerencias_aprobadas"] == "1"
    assert f[b]["origen"] == "sepa" and f[b]["campos_bloqueados"] == ""
    assert (f[b]["conflictos_resueltos"], f[b]["conflictos_pendientes"]) == ("1", "1")
    assert (f[b]["cargado_a_mano"], f[b]["revisado"]) == ("0", "1")
    assert (f[d]["revisado"], f[d]["cargado_a_mano"]) == ("0", "0")
    assert (f[d]["calidad"], f[d]["estado_calidad"], f[d]["normalizador_version"]) == (
        "80",
        "completo",
        "3",
    )
    # los metadatos son conteos: no filtran quién hizo qué
    assert str(usuario) not in "".join(str(v) for fila in f.values() for v in fila.values())


def test_exportar_es_reproducible(tmp_path, usuario):
    db(lambda c: _sembrar(c, usuario))
    r1 = asyncio.run(exportar_base(tmp_path / "test-1.csv", prefijo_ean="79999"))
    r2 = asyncio.run(exportar_base(tmp_path / "test-2.csv", prefijo_ean="79999"))
    assert r1.sha256 == r2.sha256


def test_reimportar_en_una_base_vacia_restaura_origen_y_bloqueos(tmp_path, usuario):
    a, b, d = db(lambda c: _sembrar(c, usuario))
    ruta = tmp_path / "test-base.csv.gz"
    asyncio.run(exportar_base(ruta, prefijo_ean="79999"))
    db(lambda c: c.execute("delete from productos_canonicos where ean like '79999%'"))

    r = asyncio.run(importar(ruta, aplicar=True))
    assert (r.nuevos, r.invalidas.total()) == (3, 0)
    pa, pb, pd = producto(a), producto(b), producto(d)
    assert pa["origen"] == "manual" and set(pa["campos_bloqueados"]) == {"nombre", "tamano"}
    assert (pa["nombre"], pa["tamano_valor"], pa["tamano_unidad"]) == (
        "Aceite de Girasol",
        900,
        "ml",
    )
    assert pb["origen"] == "sepa" and pd["origen"] == "off"
    # lo informativo queda en la fuente, la calidad la recalcula el normalizador local
    datos = db(
        lambda c: c.fetchval(
            "select datos->'intercambio' from producto_fuentes"
            " where ean = $1 and fuente = 'curado'",
            b,
        )
    )
    datos = json.loads(datos)
    assert datos["conflictos_resueltos"] == 1 and datos["revisado"] is True
    assert pa["estado_calidad"] is not None


def test_reimportar_sobre_la_misma_base_no_cambia_nada(tmp_path, usuario):
    db(lambda c: _sembrar(c, usuario))
    ruta = tmp_path / "test-base.csv.gz"
    asyncio.run(exportar_base(ruta, prefijo_ean="79999"))
    r = asyncio.run(importar(ruta, aplicar=False))
    assert (r.nuevos, r.cambiados, r.iguales) == (0, 0, 3)


def test_lo_humano_del_archivo_gana_sobre_un_dato_de_etl_y_se_bloquea(tmp_path, usuario):
    """Otro proyecto corrigió el nombre a mano: acá todavía figura el dato crudo del ETL."""
    a, _, _ = db(lambda c: _sembrar(c, usuario))
    ruta = tmp_path / "test-base.csv.gz"
    asyncio.run(exportar_base(ruta, prefijo_ean="79999"))

    async def degradar(c):
        async with c.transaction():
            await c.execute("select set_config('app.catalogo_write', 'on', true)")
            await c.execute(
                "update productos_canonicos set nombre = 'ACEITE GIR 900', origen = 'off',"
                " campos_bloqueados = '{}' where ean = $1",
                a,
            )

    db(degradar)
    asyncio.run(importar(ruta, aplicar=True))
    p = producto(a)
    assert p["nombre"] == "Aceite de Girasol"
    assert p["origen"] == "manual" and set(p["campos_bloqueados"]) == {"nombre", "tamano"}


def test_lo_bloqueado_localmente_no_se_pisa_con_el_archivo(tmp_path, usuario):
    a, _, _ = db(lambda c: _sembrar(c, usuario))
    ruta = tmp_path / "test-base.csv.gz"
    asyncio.run(exportar_base(ruta, prefijo_ean="79999"))

    async def editar_local(c):
        async with c.transaction():
            await c.execute("select set_config('app.catalogo_write', 'on', true)")
            await c.execute(
                "update productos_canonicos set nombre = 'Nombre local del admin' where ean = $1", a
            )

    db(editar_local)
    asyncio.run(importar(ruta, aplicar=True))
    assert producto(a)["nombre"] == "Nombre local del admin"


def test_la_ida_y_vuelta_no_cambia_el_origen_de_nadie(tmp_path, usuario):
    a, b, d = db(lambda c: _sembrar(c, usuario))
    ruta = tmp_path / "test-base.csv.gz"
    asyncio.run(exportar_base(ruta, prefijo_ean="79999"))
    r = asyncio.run(importar(ruta, aplicar=True))
    assert r.cambia_origen == 0
    assert [producto(x)["origen"] for x in (a, b, d)] == ["manual", "sepa", "off"]


def test_un_producto_manual_con_ean_de_digito_dudoso_viaja_igual(tmp_path):
    """El catálogo de origen ya lo aceptó (lo cargó una persona): no se rechaza al volver."""
    malo = "7999900000999"  # dígito verificador inválido a propósito
    db(
        lambda c: c.execute(
            "insert into productos_canonicos (ean, nombre, origen) values ($1, 'Demo', 'manual')",
            malo,
        )
    )
    ruta = tmp_path / "test-base.csv"
    asyncio.run(exportar_base(ruta, prefijo_ean="79999"))
    r = asyncio.run(importar(ruta, aplicar=False))
    assert (r.validas, r.invalidas.total()) == (1, 0)
