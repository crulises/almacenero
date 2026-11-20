from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.auth import Usuario, current_user
from app.db import get_pool
from app.services import config
from app.services.permisos import exigir, exigir_carga, puede

router = APIRouter(tags=["locales"])

_COLUMNAS = """
    l.id, l.nombre, l.direccion, l.verificado,
    st_y(l.ubicacion::geometry) as lat, st_x(l.ubicacion::geometry) as lng
"""


class LocalOut(BaseModel):
    id: UUID
    nombre: str
    direccion: str | None
    lat: float
    lng: float
    verificado: bool
    distancia_m: float | None = None  # solo en «locales cerca»


class LocalIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    direccion: str | None = Field(default=None, max_length=200)
    # Dónde está parado el usuario: sale del GPS, no se tipea.
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)

    @field_validator("nombre", "direccion")
    @classmethod
    def _recortar(cls, v: str | None) -> str | None:
        v = v.strip() if v else v
        return v or None

    @field_validator("nombre")
    @classmethod
    def _nombre_no_vacio(cls, v: str | None) -> str:
        if not v:
            raise ValueError("el nombre no puede estar vacío")
        return v


@router.get("/locales", response_model=list[LocalOut])
async def listar_locales(
    _: Usuario = Depends(current_user), pool: asyncpg.Pool = Depends(get_pool)
) -> list[LocalOut]:
    rows = await pool.fetch(f"select {_COLUMNAS} from locales l order by l.created_at")
    return [LocalOut(**dict(r)) for r in rows]


@router.get("/locales/cerca", response_model=list[LocalOut])
async def locales_cerca(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    radio_m: float | None = Query(default=None, gt=0, le=5000),
    _: Usuario = Depends(current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[LocalOut]:
    """Locales dentro de `radio_m` (por defecto, el geofence), del más cercano al más
    lejano."""
    if radio_m is None:
        radio_m = float(await config.leer(pool, "geofence_metros"))
    rows = await pool.fetch(
        f"""
        select {_COLUMNAS},
               st_distance(l.ubicacion, p.punto) as distancia_m
        from locales l,
             lateral (select st_setsrid(st_makepoint($2, $1), 4326)::geography as punto) p
        where st_dwithin(l.ubicacion, p.punto, $3)
        order by distancia_m
        limit 20
        """,
        lat,
        lng,
        radio_m,
    )
    return [LocalOut(**dict(r)) for r in rows]


@router.post("/locales", response_model=LocalOut, status_code=201)
async def crear_local(
    body: LocalIn,
    user: Usuario = Depends(current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> LocalOut:
    """Crea un local donde está parado el usuario.

    Un admin crea locales ya verificados. Un usuario común solo puede si
    `config.alta_locales_abierta` está activa (comodidad de prueba; el Doc 1 dice
    que solo el admin crea locales) y el local nace sin verificar.
    """
    exigir_carga(user)  # restringido por karma: 403 cuenta_restringida (consultar sí)
    if puede(user, "local.crear"):
        verificado = True
    elif puede(user, "local.proponer") and await config.leer(pool, "alta_locales_abierta"):
        verificado = False
    else:
        raise HTTPException(403, "por ahora solo un admin puede crear locales")

    async with pool.acquire() as conn, conn.transaction():
        if not verificado:
            maximo = int(await config.leer(conn, "max_locales_por_dia"))
            creados = await conn.fetchval(
                """
                select count(*) from locales
                where creado_por = $1 and created_at > now() - interval '1 day'
                """,
                user.id,
            )
            if creados >= maximo:
                raise HTTPException(429, "llegaste al máximo de locales nuevos por hoy")

        # Casi seguro duplicado: nombre casi idéntico a muy poca distancia. La
        # distancia sola NO bloquea (hay locales contiguos legítimos).
        duplicado = await conn.fetchrow(
            f"""
            select {_COLUMNAS}
            from locales l
            where st_dwithin(l.ubicacion,
                             st_setsrid(st_makepoint($2, $1), 4326)::geography, $3)
              and similarity(lower(l.nombre), lower($4)) >= $5
            order by similarity(lower(l.nombre), lower($4)) desc
            limit 1
            """,
            body.lat,
            body.lng,
            float(await config.leer(conn, "local_duplicado_metros")),
            body.nombre,
            float(await config.leer(conn, "local_duplicado_similitud")),
        )
        if duplicado is not None:
            raise HTTPException(
                409,
                detail={
                    "codigo": "local_duplicado",
                    "mensaje": "ya hay un local con ese nombre acá",
                    "local": LocalOut(**dict(duplicado)).model_dump(mode="json"),
                },
            )

        row = await conn.fetchrow(
            f"""
            with nuevo as (
                insert into locales (nombre, direccion, ubicacion, creado_por, verificado)
                values ($1, $2, st_setsrid(st_makepoint($4, $3), 4326)::geography, $5, $6)
                returning *
            )
            select {_COLUMNAS} from nuevo l
            """,
            body.nombre,
            body.direccion,
            body.lat,
            body.lng,
            user.id,
            verificado,
        )
    return LocalOut(**dict(row))


@router.post("/locales/{local_id}/verificar", response_model=LocalOut)
async def verificar_local(
    local_id: UUID,
    _: Usuario = Depends(exigir("local.verificar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> LocalOut:
    row = await pool.fetchrow(
        f"""
        with actualizado as (
            update locales set verificado = true where id = $1 returning *
        )
        select {_COLUMNAS} from actualizado l
        """,
        local_id,
    )
    if row is None:
        raise HTTPException(404, "local no encontrado")
    return LocalOut(**dict(row))
