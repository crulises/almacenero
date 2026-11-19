from decimal import Decimal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.v1.productos import es_ean_de_balanza
from app.auth import Usuario, current_user
from app.db import get_pool
from app.services import config
from app.services.karma import karma_por_carga, sumar_karma

router = APIRouter(tags=["precios"])


class PrecioIn(BaseModel):
    ean: str
    local_id: UUID
    precio: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    # Dónde está el usuario al cargar (geofence, Doc 1): el celular la informa.
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    precision_m: float | None = Field(default=None, ge=0)


class PrecioCreado(BaseModel):
    precio_id: UUID
    karma: int  # karma del usuario ya actualizado


async def _exigir_cerca(
    conn: asyncpg.Connection, distancia_m: float, precision_m: float | None
) -> None:
    """Geofence: solo se carga estando cerca del local (Doc 1, «Ubicación»).

    Un GPS impreciso no se rechaza a ciegas: se pide reintentar. La ubicación la
    informa el celular, así que esto frena el ruido, no a quien la simule.
    """
    radio = float(await config.leer(conn, "geofence_metros"))
    precision_max = float(await config.leer(conn, "geofence_precision_max_m"))
    if precision_m is not None and precision_m > precision_max:
        raise HTTPException(
            403,
            detail={
                "codigo": "precision_baja",
                "mensaje": "la ubicación es muy imprecisa: esperá a que mejore el GPS",
                "precision_m": round(precision_m),
                "precision_max_m": round(precision_max),
            },
        )
    if distancia_m > radio:
        raise HTTPException(
            403,
            detail={
                "codigo": "fuera_de_rango",
                "mensaje": f"estás a {round(distancia_m)} m del local",
                "distancia_m": round(distancia_m),
                "radio_m": round(radio),
            },
        )


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
        distancia = await conn.fetchval(
            """
            select st_distance(ubicacion, st_makepoint($2::float8, $3::float8)::geography)
            from locales where id = $1
            """,
            body.local_id,
            body.lng,
            body.lat,
        )
        if distancia is None:
            raise HTTPException(404, "local no encontrado")
        await _exigir_cerca(conn, distancia, body.precision_m)

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
