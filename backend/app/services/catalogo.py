"""Escritura a mano en el catálogo: el único camino para corregir o dar de alta un producto.

Lo usan la corrección directa del admin (`PATCH /admin/productos`), el alta simple del panel
y la aprobación de una sugerencia de moderador: los tres hacen exactamente lo mismo, así
que lo corregido queda **bloqueado contra el ETL** y la calidad se recalcula siempre.
"""

from decimal import Decimal
from uuid import UUID

import asyncpg
from pydantic import BaseModel, Field, model_validator

from app.services import calidad

CAMPOS = ("nombre", "marca", "tamano_valor", "tamano_unidad", "pack_cantidad", "presentacion")


class Cambios(BaseModel):
    """Lo que una persona puede decir de un producto. Solo viajan los campos presentes:
    un campo ausente no se toca; presente y vacío, se borra."""

    nombre: str | None = Field(default=None, min_length=1, max_length=200)
    marca: str | None = Field(default=None, max_length=100)
    tamano_valor: Decimal | None = Field(default=None, gt=0)
    tamano_unidad: str | None = Field(default=None, pattern="^(g|kg|ml|l|u)$")
    pack_cantidad: int | None = Field(default=None, ge=1, le=1000)
    presentacion: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def _validar(self):
        if "nombre" in self.model_fields_set and (self.nombre is None or not self.nombre.strip()):
            raise ValueError("el nombre no puede estar vacío")
        toca_tamano = {"tamano_valor", "tamano_unidad"} & self.model_fields_set
        if toca_tamano and (self.tamano_valor is None) != (self.tamano_unidad is None):
            raise ValueError("tamaño y unidad van juntos (o los dos vacíos)")
        return self

    def a_dict(self) -> dict:
        """Solo los campos presentes, con el texto limpio (vacío = borrar)."""
        d: dict = {}
        for campo in CAMPOS:
            if campo not in self.model_fields_set:
                continue
            v = getattr(self, campo)
            if isinstance(v, str):
                v = v.strip() or None
                if campo == "presentacion" and v:
                    v = v.lower()
            d[campo] = v
        return d


def bloqueos(cambios: dict) -> list[str]:
    """Qué campos del catálogo quedan bloqueados contra el ETL al aplicar estos cambios."""
    b = []
    for campo in ("nombre", "marca", "presentacion"):
        if campo in cambios:
            b.append(campo)
    if {"tamano_valor", "tamano_unidad", "pack_cantidad"} & cambios.keys():
        b.append("tamano")
    return b


async def aplicar(conn: asyncpg.Connection, producto_id: UUID, cambios: dict) -> tuple[dict, dict]:
    """Aplica `cambios` a un producto y lo bloquea. -> (antes, despues) de esos campos.
    Dentro de la transacción de quien llama (que también audita). `None` si no existe."""
    antes = await conn.fetchrow(
        f"select {', '.join(CAMPOS)} from productos_canonicos where id = $1 for update",
        producto_id,
    )
    if antes is None:
        return {}, {}
    await conn.execute("select set_config('app.catalogo_write', 'on', true)")
    sets = [f"{k} = ${i + 2}" for i, k in enumerate(cambios)]
    await conn.execute(
        f"update productos_canonicos set {', '.join(sets)}, campos_bloqueados = "
        f"array(select distinct unnest(campos_bloqueados || ${len(cambios) + 2}::text[])) "
        "where id = $1",
        producto_id,
        *cambios.values(),
        bloqueos(cambios),
    )
    await calidad.recalcular(conn, producto_id=producto_id)
    return {k: antes[k] for k in cambios}, dict(cambios)


async def crear(conn: asyncpg.Connection, ean: str, cambios: dict) -> UUID:
    """Alta de un producto nuevo: origen `manual` y todo lo que se dio queda bloqueado. Lo que
    se dejó vacío no se bloquea: un ETL todavía puede completarlo."""
    cambios = {k: v for k, v in cambios.items() if v is not None}
    await conn.execute("select set_config('app.catalogo_write', 'on', true)")
    cols = list(cambios)
    producto_id = await conn.fetchval(
        f"insert into productos_canonicos (ean, origen, campos_bloqueados, {', '.join(cols)}) "
        f"values ($1, 'manual', $2::text[], {', '.join(f'${i + 3}' for i in range(len(cols)))}) "
        "returning id",
        ean,
        bloqueos(cambios),
        *cambios.values(),
    )
    await calidad.recalcular(conn, producto_id=producto_id)
    return producto_id
