"""Reclamar una cuenta huérfana para una cuenta ligada a Google (corte 21).

Una huérfana es una cuenta anónima a la que ya no se puede volver (se borraron los datos de
la app o se reinstaló). No se fusionan solas: no hay forma confiable de saber que dos cuentas
son de la misma persona. El admin lo decide en el panel, con motivo, y queda auditado
(docs/superpowers/specs/2026-11-26-cuentas-ligables-design.md, «Huérfanas y reclamo»).
"""

from uuid import UUID

import asyncpg

from app.services import auditoria

# Tablas con autoría del usuario que pasan a la cuenta ligada. No se tocan `eventos` ni
# `auditoria_admin`: son rastros de lo que pasó, no cargas.
_REASIGNAR = (
    ("precios", "user_id"),
    ("locales", "creado_por"),
    ("sugerencias_catalogo", "usuario_id"),
    ("avisos_catalogo", "usuario_id"),
)


class ReclamoInvalido(Exception):
    """El reclamo no se puede hacer (`http`: 404 / 409 / 422) y no cambió nada."""

    def __init__(self, http: int, mensaje: str):
        super().__init__(mensaje)
        self.http = http
        self.mensaje = mensaje


async def reclamar(
    pool: asyncpg.Pool, admin_id: UUID, huerfana_id: UUID, destino_id: UUID, motivo: str
) -> int:
    """Pasa el karma y las cargas de la huérfana a la cuenta ligada y deja a la huérfana en
    estado `fusionada`. Todo en una transacción. Devuelve cuántas filas NO pudieron pasar por
    chocar con una restricción de unicidad (las validaciones que los dos hicieron del mismo
    precio): esas quedan con la huérfana."""
    if huerfana_id == destino_id:
        raise ReclamoInvalido(422, "la cuenta huérfana y la ligada tienen que ser distintas")
    async with pool.acquire() as conn, conn.transaction():
        filas = await conn.fetch(
            "select id, estado, es_anonimo, karma from usuarios where id = any($1) "
            "order by id for update",
            [huerfana_id, destino_id],
        )
        por_id = {f["id"]: f for f in filas}
        if huerfana_id not in por_id or destino_id not in por_id:
            raise ReclamoInvalido(404, "usuario no encontrado")
        huerfana, destino = por_id[huerfana_id], por_id[destino_id]
        if not huerfana["es_anonimo"]:
            raise ReclamoInvalido(409, "la cuenta huérfana ya está ligada a Google")
        if huerfana["estado"] != "activo":
            raise ReclamoInvalido(409, f"la cuenta huérfana está {huerfana['estado']}")
        if destino["es_anonimo"]:
            raise ReclamoInvalido(409, "la cuenta destino no está ligada a Google")
        if destino["estado"] != "activo":
            raise ReclamoInvalido(409, f"la cuenta destino está {destino['estado']}")

        await conn.execute("select set_config('app.karma_write', 'on', true)")
        await conn.execute("select set_config('app.estado_write', 'on', true)")
        karma_destino = await conn.fetchval(
            "update usuarios set karma = karma + $2 where id = $1 returning karma",
            destino_id,
            huerfana["karma"],
        )
        for tabla, columna in _REASIGNAR:
            await conn.execute(
                f"update {tabla} set {columna} = $2 where {columna} = $1",  # noqa: S608
                huerfana_id,
                destino_id,
            )
        await conn.execute(
            """
            update validaciones v set user_id = $2
            where v.user_id = $1
              and not exists (select 1 from validaciones w
                              where w.precio_id = v.precio_id and w.user_id = $2)
            """,
            huerfana_id,
            destino_id,
        )
        sin_pasar = await conn.fetchval(
            "select count(*) from validaciones where user_id = $1", huerfana_id
        )
        await conn.execute(
            "update usuarios set estado = 'fusionada', fusionada_en = $2, karma = 0 where id = $1",
            huerfana_id,
            destino_id,
        )
        await auditoria.registrar(
            conn,
            admin_id,
            "usuario.reclamar",
            "usuario",
            destino_id,
            {"huerfana": str(huerfana_id), "karma_huerfana": huerfana["karma"]},
            {"karma_destino": karma_destino, "filas_sin_pasar": sin_pasar},
            nota=motivo,
        )
    return sin_pasar
