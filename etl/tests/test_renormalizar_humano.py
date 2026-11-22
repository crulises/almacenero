# ruff: noqa: E501
"""Lo que carga una persona fuera del estándar (Doc 8) se limpia, completa los campos vacíos
y deja un aviso con el porqué (sin tocar el karma). Contra Postgres local real."""

import uuid

from etl.renormalizar import _avisar, nueva_fila
from etl.tests.test_off_db import db, ean, limpio  # noqa: F401


def fila(**kw):
    base = {
        "id": uuid.uuid4(), "ean": ean(1), "nombre": "Aceite Girasol", "marca": None,
        "tamano_valor": None, "tamano_unidad": None, "imagen_url": None, "presentacion": None,
        "pack_cantidad": None, "origen": "manual", "campos_bloqueados": ["nombre"],
        "calidad": 0, "estado_calidad": "parcial", "calidad_motivos": [],
        "normalizador_version": 1,
    }  # fmt: skip
    return {**base, **kw}


def test_el_nombre_de_una_persona_con_todo_adentro_se_limpia_y_completa():
    r = fila(nombre="Aceite Cocinero Girasol 900 ml Botella")
    n = nueva_fila(r)
    assert n["nombre"] == "Aceite Girasol"
    assert n["marca"] == "Cocinero"
    assert (float(n["tamano_valor"]), n["tamano_unidad"]) == (900.0, "ml")
    assert n["presentacion"] == "botella"
    assert n["_estandares"][0] == "nombre"
    assert {"marca", "tamano", "presentacion"} <= set(n["_estandares"])
    assert "nombre" in n["campos_bloqueados"]  # sigue bloqueado


def test_nunca_pisa_un_campo_ya_cargado_por_la_persona():
    r = fila(
        nombre="Aceite Cocinero Girasol 900 ml",
        marca="Cañuelas",
        campos_bloqueados=["nombre", "marca"],
    )
    n = nueva_fila(r)
    assert n["marca"] == "Cañuelas"
    r = fila(nombre="Aceite Girasol 900 ml", tamano_valor=1, tamano_unidad="l",
             campos_bloqueados=["nombre", "tamano"])  # fmt: skip
    assert (float(nueva_fila(r)["tamano_valor"]), nueva_fila(r)["tamano_unidad"]) == (1.0, "l")


def test_es_idempotente_y_lo_estandar_no_genera_aviso():
    n = nueva_fila(fila(nombre="Aceite Cocinero Girasol 900 ml Botella"))
    segunda = nueva_fila({**n, "id": n["id"]})
    assert segunda["nombre"] == n["nombre"] and segunda["_estandares"] == []
    ok = nueva_fila(fila(nombre="Aceite Girasol", marca="Cocinero"))
    assert ok["nombre"] == "Aceite Girasol" and ok["_estandares"] == []


def test_un_nombre_inservible_de_una_persona_no_se_reemplaza():
    n = nueva_fila(fila(nombre="12345"))
    assert n["nombre"] == "12345"


def test_lo_que_no_es_humano_no_genera_aviso():
    n = nueva_fila(
        fila(nombre="ACEITE COCINERO GIRASOL 900 ML", origen="sepa", campos_bloqueados=[])
    )
    assert n["_estandares"] == [] and n["nombre"] != "ACEITE COCINERO GIRASOL 900 ML"


def test_estandares_por_tipo_de_defecto():
    r = fila(nombre="ACEITE DE GIRASOL")
    n = nueva_fila(r)
    assert n["nombre"] == "Aceite de Girasol" and n["_estandares"] == ["mayusculas"]
    r = fila(nombre="Aceite p/ ensalada")
    assert "abreviaturas" in nueva_fila(r)["_estandares"]
    r = fila(nombre="Fideos  Tirabuzón ..")
    n = nueva_fila(r)
    assert n["_estandares"] == ["limpieza"], n


def test_avisar_deja_el_aviso_al_autor_sin_tocar_su_karma():
    r = fila(nombre="Aceite Cocinero Girasol 900 ml Botella")
    n = nueva_fila(r)
    uid, auth = uuid.uuid4(), uuid.uuid4()

    async def correr(c):
        await c.execute(
            "insert into usuarios (id, auth_id, alias) values ($1, $2, 'autor-test')", uid, auth
        )
        try:
            await c.execute(
                "insert into productos_canonicos (id, ean, nombre, origen) values ($1, $2, $3, 'manual')",
                r["id"], r["ean"], r["nombre"],
            )  # fmt: skip
            await c.execute(
                "insert into sugerencias_catalogo (producto_id, ean, usuario_id, cambios, estado, "
                "resuelto_por, resuelto_en) values ($1, $2, $3, '{\"nombre\": \"x\"}', 'aprobada', "
                "$3, now())",
                r["id"], r["ean"], uid,
            )  # fmt: skip
            hechos = await _avisar(c, {r["ean"]: (r, n)})
            avisos = await c.fetch(
                "select estandares, antes->>'nombre' as a, despues->>'nombre' as d "
                "from avisos_catalogo where usuario_id = $1",
                uid,
            )
            karma = await c.fetchval("select karma from usuarios where id = $1", uid)
            return hechos, [dict(a) for a in avisos], karma
        finally:
            await c.execute("delete from avisos_catalogo where usuario_id = $1", uid)
            await c.execute("delete from sugerencias_catalogo where usuario_id = $1", uid)
            await c.execute("delete from productos_canonicos where id = $1", r["id"])
            await c.execute("delete from usuarios where id = $1", uid)

    hechos, avisos, karma = db(correr)
    assert hechos == 1 and karma == 0
    assert avisos[0]["a"] == "Aceite Cocinero Girasol 900 ml Botella"
    assert avisos[0]["d"] == "Aceite Girasol" and "marca" in avisos[0]["estandares"]
