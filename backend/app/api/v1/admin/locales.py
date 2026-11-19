from datetime import datetime
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from app.api.v1.admin.consulta import Consulta, escapar_like
from app.api.v1.admin.paginas import Pagina
from app.auth import Usuario
from app.db import get_pool
from app.services import auditoria
from app.services.permisos import exigir

router = APIRouter(tags=["admin"])

MAX_MASIVO = 500


class LocalAdminOut(BaseModel):
    id: UUID
    nombre: str
    direccion: str | None
    lat: float
    lng: float
    verificado: bool
    fuente: str  # manual | osm | sepa
    creado_por_alias: str | None
    precios: int
    refs: list[str]  # vínculos con las fuentes del ETL («osm:node/1», «sepa:...»)
    created_at: datetime


class LocalPatch(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    direccion: str | None = Field(default=None, max_length=200)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    verificado: bool | None = None

    @field_validator("nombre", "direccion")
    @classmethod
    def _recortar(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else None

    @model_validator(mode="after")
    def _validar(self):
        if (self.lat is None) != (self.lng is None):
            raise ValueError("lat y lng van juntos")
        for campo in ("nombre", "verificado"):
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"{campo} no puede ser nulo")
        if "nombre" in self.model_fields_set and not self.nombre:
            raise ValueError("el nombre no puede estar vacío")
        return self


class IdsIn(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=MAX_MASIVO)


class FusionIn(BaseModel):
    destino_id: UUID
    origen_ids: list[UUID] = Field(min_length=1, max_length=MAX_MASIVO)


class ResultadoMasivo(BaseModel):
    afectados: int
    omitidos: list[UUID] = []
    motivo: str | None = None


_SELECT = """
    select l.id, l.nombre, l.direccion, l.verificado, l.fuente, l.created_at,
           st_y(l.ubicacion::geometry) as lat, st_x(l.ubicacion::geometry) as lng,
           u.alias as creado_por_alias,
           (select count(*) from precios p where p.local_id = l.id) as precios,
           coalesce((select array_agg(f.fuente || ':' || f.ref order by f.fuente, f.ref)
                       from local_fuentes f where f.local_id = l.id), '{}') as refs
    from locales l left join usuarios u on u.id = l.creado_por
"""

_INSTANTANEA = """
    select l.nombre, l.direccion, l.verificado, l.fuente,
           st_y(l.ubicacion::geometry) as lat, st_x(l.ubicacion::geometry) as lng
    from locales l
"""


@router.get("/locales", response_model=Pagina[LocalAdminOut])
async def listar_locales(
    verificado: bool | None = None,
    fuente: str | None = Query(None, pattern="^(manual|osm|sepa)$"),
    q: str | None = Query(None, max_length=100, description="nombre o dirección"),
    sin_precios: bool = False,
    orden: str = Query("alta", pattern="^(alta|nombre|precios)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: Usuario = Depends(exigir("local.verificar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Pagina[LocalAdminOut]:
    c = Consulta()
    if verificado is not None:
        c.donde("l.verificado = {}", verificado)
    if fuente:
        c.donde("l.fuente = {}", fuente)
    if q and q.strip():
        p = c.param(f"%{escapar_like(q.strip().lower())}%")
        c.condiciones.append(
            f"(lower(l.nombre) like {p} or lower(coalesce(l.direccion, '')) like {p})"
        )
    if sin_precios:
        c.condiciones.append("not exists (select 1 from precios p where p.local_id = l.id)")
    total = await pool.fetchval(f"select count(*) from locales l {c.where}", *c.args)
    orden_sql = {
        "alta": "l.created_at desc, l.id",
        "nombre": "lower(l.nombre), l.id",
        "precios": "precios desc, l.id",
    }[orden]
    lim, off = c.param(limit), c.param(offset)
    rows = await pool.fetch(
        f"{_SELECT} {c.where} order by {orden_sql} limit {lim} offset {off}", *c.args
    )
    return Pagina(total=total, items=[LocalAdminOut(**dict(r)) for r in rows])


@router.patch("/locales/{local_id}", response_model=LocalAdminOut)
async def corregir_local(
    local_id: UUID,
    body: LocalPatch,
    admin: Usuario = Depends(exigir("local.editar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> LocalAdminOut:
    """Corrige nombre, dirección, ubicación y/o verificación. Solo cambia lo que viene."""
    async with pool.acquire() as conn, conn.transaction():
        antes = await conn.fetchrow(f"{_INSTANTANEA} where l.id = $1 for update of l", local_id)
        if antes is None:
            raise HTTPException(404, "local no encontrado")
        sets, args = [], [local_id]
        for campo in ("nombre", "direccion", "verificado"):
            if campo in body.model_fields_set:
                args.append(getattr(body, campo))
                sets.append(f"{campo} = ${len(args)}")
        if body.lat is not None:
            args += [body.lng, body.lat]
            sets.append(
                f"ubicacion = st_setsrid(st_makepoint(${len(args) - 1}, ${len(args)}), 4326)"
                "::geography"
            )
        if not sets:
            raise HTTPException(422, "no hay nada para cambiar")
        await conn.execute(f"update locales set {', '.join(sets)} where id = $1", *args)
        despues = await conn.fetchrow(f"{_INSTANTANEA} where l.id = $1", local_id)
        cambios = {k: v for k, v in dict(despues).items() if v != antes[k]}
        await auditoria.registrar(
            conn,
            admin.id,
            "local.corregir",
            "local",
            local_id,
            {k: antes[k] for k in cambios},
            cambios,
        )
        row = await conn.fetchrow(f"{_SELECT} where l.id = $1", local_id)
    return LocalAdminOut(**dict(row))


@router.post("/locales/validar", response_model=ResultadoMasivo)
async def validar_locales(
    body: IdsIn,
    admin: Usuario = Depends(exigir("local.verificar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ResultadoMasivo:
    """Acción masiva: marca como verificados los locales indicados."""
    ids = list(dict.fromkeys(body.ids))
    async with pool.acquire() as conn, conn.transaction():
        hechos = await conn.fetch(
            """
            update locales set verificado = true
            where id = any($1::uuid[]) and not verificado returning id
            """,
            ids,
        )
        for r in hechos:
            await auditoria.registrar(
                conn,
                admin.id,
                "local.validar",
                "local",
                r["id"],
                {"verificado": False},
                {"verificado": True},
            )
    ya = {r["id"] for r in hechos}
    return ResultadoMasivo(
        afectados=len(ya),
        omitidos=[i for i in ids if i not in ya],
        motivo="inexistente o ya verificado",
    )


@router.post("/locales/fusionar", response_model=LocalAdminOut)
async def fusionar_locales(
    body: FusionIn,
    admin: Usuario = Depends(exigir("local.fusionar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> LocalAdminOut:
    """Fusiona duplicados: los precios, ítems y vínculos de los orígenes pasan al destino
    y los orígenes se borran."""
    origenes = list(dict.fromkeys(body.origen_ids))
    if body.destino_id in origenes:
        raise HTTPException(422, "el destino no puede estar entre los orígenes")
    async with pool.acquire() as conn, conn.transaction():
        todos = [body.destino_id, *origenes]
        existen = await conn.fetchval(
            "select count(*) from locales where id = any($1::uuid[])", todos
        )
        if existen != len(todos):
            raise HTTPException(404, "algún local no existe")
        for origen in origenes:
            antes = dict(await conn.fetchrow(f"{_INSTANTANEA} where l.id = $1", origen))
            precios = await conn.fetchval(
                "with m as (update precios set local_id = $2 where local_id = $1 returning 1) "
                "select count(*) from m",
                origen,
                body.destino_id,
            )
            await conn.execute(
                "update items_genericos set local_id = $2 where local_id = $1",
                origen,
                body.destino_id,
            )
            await conn.execute(
                "update local_fuentes set local_id = $2 where local_id = $1",
                origen,
                body.destino_id,
            )
            await conn.execute("delete from locales where id = $1", origen)
            await auditoria.registrar(
                conn,
                admin.id,
                "local.fusionar",
                "local",
                origen,
                antes,
                {"fusionado_en": body.destino_id, "precios_movidos": precios},
            )
        row = await conn.fetchrow(f"{_SELECT} where l.id = $1", body.destino_id)
    return LocalAdminOut(**dict(row))


@router.post("/locales/borrar", response_model=ResultadoMasivo)
async def borrar_locales(
    body: IdsIn,
    admin: Usuario = Depends(exigir("local.borrar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ResultadoMasivo:
    """Borra locales SIN precios ni ítems (los demás se omiten: para esos, fusionar)."""
    ids = list(dict.fromkeys(body.ids))
    async with pool.acquire() as conn, conn.transaction():
        filas = await conn.fetch(
            """
            select l.id from locales l
            where l.id = any($1::uuid[])
              and not exists (select 1 from precios p where p.local_id = l.id)
              and not exists (select 1 from items_genericos i where i.local_id = l.id)
            for update of l
            """,
            ids,
        )
        for r in filas:
            antes = dict(await conn.fetchrow(f"{_INSTANTANEA} where l.id = $1", r["id"]))
            await conn.execute("delete from locales where id = $1", r["id"])
            await auditoria.registrar(conn, admin.id, "local.borrar", "local", r["id"], antes)
    hechos = {r["id"] for r in filas}
    return ResultadoMasivo(
        afectados=len(hechos),
        omitidos=[i for i in ids if i not in hechos],
        motivo="inexistente, o tiene precios o ítems (fusionalo en otro local)",
    )
