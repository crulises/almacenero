from datetime import datetime
from decimal import Decimal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import Usuario, current_user
from app.db import get_pool
from app.services import config
from app.services.frescura import clasificar

router = APIRouter(tags=["productos"])


class ProductoOut(BaseModel):
    id: UUID
    ean: str
    nombre: str
    marca: str | None
    tamano_valor: Decimal | None
    tamano_unidad: str | None
    imagen_url: str | None


class PrecioOut(BaseModel):
    id: UUID
    local_id: UUID
    local_nombre: str
    precio: Decimal
    fecha: datetime
    user_id: UUID


class PrecioVigenteOut(BaseModel):
    """El último precio de un producto en un local, con su frescura."""

    local_id: UUID
    local_nombre: str
    local_verificado: bool
    lat: float
    lng: float
    precio: Decimal
    fecha: datetime
    edad_dias: int
    frescura: str  # verde | amarillo | rojo
    vencido: bool  # más viejo que la ventana de frescura


def es_ean_de_balanza(ean: str) -> bool:
    """Un EAN que empieza con `2` es interno del local (peso/precio variable):
    se trata como genérico, y los genéricos están desactivados en v0.0.1."""
    return ean.startswith("2")


@router.get("/productos/{ean}", response_model=ProductoOut)
async def buscar_producto(
    ean: str, _: Usuario = Depends(current_user), pool: asyncpg.Pool = Depends(get_pool)
) -> ProductoOut:
    if es_ean_de_balanza(ean):
        raise HTTPException(422, "EAN de balanza: productos genéricos no habilitados")
    row = await pool.fetchrow(
        """
        select id, ean, nombre, marca, tamano_valor, tamano_unidad, imagen_url
        from productos_canonicos where ean = $1
        """,
        ean,
    )
    if row is None:
        raise HTTPException(404, "producto no encontrado en el catálogo")
    return ProductoOut(**dict(row))


@router.get("/productos/{ean}/precios", response_model=list[PrecioOut])
async def historial_precios(
    ean: str,
    local_id: UUID | None = None,
    _: Usuario = Depends(current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[PrecioOut]:
    rows = await pool.fetch(
        """
        select p.id, p.local_id, l.nombre as local_nombre, p.precio, p.fecha,
               p.user_id
        from precios p
        join productos_canonicos pc on pc.id = p.producto_canonico_id
        join locales l on l.id = p.local_id
        where pc.ean = $1 and ($2::uuid is null or p.local_id = $2)
        order by p.fecha desc
        limit 200
        """,
        ean,
        local_id,
    )
    return [PrecioOut(**dict(r)) for r in rows]


@router.get("/productos/{ean}/precios/vigentes", response_model=list[PrecioVigenteOut])
async def precios_vigentes(
    ean: str,
    _: Usuario = Depends(current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[PrecioVigenteOut]:
    """El último precio de cada local, del más barato al más caro.

    Con esto se arma la lista y el mapa de «cuánto sale en cada lugar». El historial
    completo sigue en `/precios`.
    """
    rows = await pool.fetch(
        """
        select distinct on (p.local_id)
               p.local_id, l.nombre as local_nombre, l.verificado as local_verificado,
               st_y(l.ubicacion::geometry) as lat, st_x(l.ubicacion::geometry) as lng,
               p.precio, p.fecha, (current_date - p.fecha::date) as edad_dias
        from precios p
        join productos_canonicos pc on pc.id = p.producto_canonico_id
        join locales l on l.id = p.local_id
        where pc.ean = $1
        order by p.local_id, p.fecha desc
        """,
        ean,
    )
    verde = int(await config.leer(pool, "umbral_verde_dias"))
    amarillo = int(await config.leer(pool, "umbral_amarillo_dias"))
    ventana = int(await config.leer(pool, "ventana_frescura_dias"))
    vigentes = [
        PrecioVigenteOut(
            **dict(r),
            frescura=clasificar(r["edad_dias"], verde, amarillo),
            vencido=r["edad_dias"] > ventana,
        )
        for r in rows
    ]
    return sorted(vigentes, key=lambda v: (v.precio, v.edad_dias))
