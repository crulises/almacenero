from decimal import Decimal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.v1.productos import es_ean_de_balanza
from app.auth import Usuario
from app.db import get_pool
from app.services import config
from app.services.karma import karma_por_carga, sumar_karma
from app.services.permisos import exigir

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
    karma_sumado: int  # 0 si repetía un precio ya cargado por el mismo usuario


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


async def _exigir_bajo_limite(conn: asyncpg.Connection, user_id: UUID) -> None:
    """Tope de cargas por usuario por hora y por día (`config`). Frena a quien
    automatiza; el uso normal (cargar en el súper) queda muy lejos."""
    for clave, ventana, texto in (
        ("max_precios_por_hora", "1 hour", "esta hora"),
        ("max_precios_por_dia", "1 day", "hoy"),
    ):
        maximo = int(await config.leer(conn, clave))
        cargados = await conn.fetchval(
            f"select count(*) from precios where user_id = $1 "
            f"and created_at > now() - interval '{ventana}'",
            user_id,
        )
        if cargados >= maximo:
            raise HTTPException(
                429,
                detail={
                    "codigo": "limite_cargas",
                    "mensaje": f"llegaste al máximo de precios cargados {texto}",
                },
            )


@router.post("/precios", response_model=PrecioCreado, status_code=201)
async def cargar_precio(
    body: PrecioIn,
    user: Usuario = Depends(exigir("precio.cargar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> PrecioCreado:
    if es_ean_de_balanza(body.ean):
        raise HTTPException(422, "EAN de balanza: productos genéricos no habilitados")

    async with pool.acquire() as conn, conn.transaction():
        # Serializa las cargas del mismo usuario: dos requests a la vez no se cuelan
        # por debajo del tope.
        await conn.execute("select 1 from usuarios where id = $1 for update", user.id)
        await _exigir_bajo_limite(conn, user.id)
        producto_id = await conn.fetchval(
            "select id from productos_canonicos "
            "where ean = $1 and estado_calidad is distinct from 'descartado'",
            body.ean,
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

        # Repetir el mismo precio en el mismo local dentro de la ventana de frescura
        # no suma karma (corta el farmeo). El precio se guarda igual: confirma que
        # sigue vigente.
        repetido = await conn.fetchval(
            """
            select exists (
                select 1 from precios
                where user_id = $1 and producto_canonico_id = $2 and local_id = $3
                  and precio = $4 and created_at > now() - make_interval(days => $5)
            )
            """,
            user.id,
            producto_id,
            body.local_id,
            body.precio,
            int(await config.leer(conn, "ventana_frescura_dias")),
        )

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
        sumado = 0 if repetido else karma_por_carga()
        karma = await sumar_karma(conn, user.id, sumado)
    return PrecioCreado(precio_id=precio_id, karma=karma, karma_sumado=sumado)
