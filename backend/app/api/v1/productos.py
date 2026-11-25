from datetime import datetime
from decimal import Decimal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
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
    pack_cantidad: int | None = None
    presentacion: str | None = None


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
    distancia_m: float | None = None
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
        select id, ean, nombre, marca, tamano_valor, tamano_unidad, imagen_url,
               pack_cantidad, presentacion
        from productos_canonicos
        where ean = $1 and estado_calidad is distinct from 'descartado'
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
    lat: float | None = Query(None, ge=-90, le=90),
    lng: float | None = Query(None, ge=-180, le=180),
    radio_m: int | None = Query(None, gt=0),
    referencia: bool = Query(False),
    _: Usuario = Depends(current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[PrecioVigenteOut]:
    """El último precio de cada local, del más barato al más caro.

    Con `lat` y `lng` trae solo los locales dentro de `radio_m` (por defecto
    `config.radio_precios_m`) y agrega la distancia: sin esto, precios de locales a
    miles de kilómetros se mezclarían con los de tu zona. Sin ubicación trae todos.

    `radio_m` puede ampliarse hasta el radio de referencia (`config.radio_referencia_km`): es lo
    que usa «Recientes» cuando no hay nada en la zona. `referencia=true` pide justo ese radio
    (la app no necesita conocer el número). Lo que venga de ahí es **referencia**, no precio de
    la zona: la app lo marca con su distancia.
    """
    if (lat is None) != (lng is None):
        raise HTTPException(422, "lat y lng van juntos")
    if referencia and lat is None:
        raise HTTPException(422, "referencia necesita lat y lng")
    if lat is None:
        radio = None
    else:
        zona = int(await config.leer(pool, "radio_precios_m"))
        tope = max(zona, int(await config.leer(pool, "radio_referencia_km")) * 1000)
        radio = tope if referencia else (radio_m or zona)
        if radio > tope:
            raise HTTPException(422, f"radio_m no puede pasar de {tope} m")
    rows = await pool.fetch(
        """
        select * from (
          select distinct on (p.local_id)
                 p.local_id, l.nombre as local_nombre, l.verificado as local_verificado,
                 st_y(l.ubicacion::geometry) as lat, st_x(l.ubicacion::geometry) as lng,
                 p.precio, p.fecha, (current_date - p.fecha::date) as edad_dias,
                 case when $2::float8 is null then null
                      else st_distance(l.ubicacion,
                           st_makepoint($3::float8, $2::float8)::geography) end
                   as distancia_m
          from precios p
          join productos_canonicos pc on pc.id = p.producto_canonico_id
          join locales l on l.id = p.local_id
          where pc.ean = $1
          order by p.local_id, p.fecha desc
        ) v
        where $4::float8 is null or v.distancia_m <= $4::float8
        """,
        ean,
        lat,
        lng,
        None if radio is None else float(radio),
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
