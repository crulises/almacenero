from decimal import Decimal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.v1.productos import es_ean_de_balanza
from app.auth import Usuario, current_user
from app.db import get_pool
from app.services.karma import karma_por_carga, sumar_karma

router = APIRouter(tags=["precios"])


class PrecioIn(BaseModel):
    ean: str
    local_id: UUID
    precio: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class PrecioCreado(BaseModel):
    precio_id: UUID
    karma: int  # karma del usuario ya actualizado


@router.post("/precios", response_model=PrecioCreado, status_code=201)
async def cargar_precio(
    body: PrecioIn,
    user: Usuario = Depends(current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> PrecioCreado:
    if es_ean_de_balanza(body.ean):
        raise HTTPException(422, "EAN de balanza: productos genéricos no habilitados")

    async with pool.acquire() as conn, conn.transaction():
        producto_id = await conn.fetchval(
            "select id from productos_canonicos where ean = $1", body.ean
        )
        if producto_id is None:
            raise HTTPException(404, "producto no encontrado en el catálogo")
        if not await conn.fetchval("select 1 from locales where id = $1", body.local_id):
            raise HTTPException(404, "local no encontrado")

        # TODO(v0.0.2): geofence (config.geofence_metros) antes de aceptar la carga.
        precio_id = await conn.fetchval(
            """
            insert into precios (producto_canonico_id, local_id, precio, user_id)
            values ($1, $2, $3, $4) returning id
            """,
            producto_id,
            body.local_id,
            body.precio,
            user.id,
        )
        karma = await sumar_karma(conn, user.id, karma_por_carga())
    return PrecioCreado(precio_id=precio_id, karma=karma)
