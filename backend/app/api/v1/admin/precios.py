from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.v1.admin.auditoria import AuditoriaOut, historial
from app.api.v1.admin.consulta import Consulta
from app.api.v1.admin.locales import MAX_MASIVO, ResultadoMasivo
from app.api.v1.admin.paginas import Pagina
from app.auth import Usuario
from app.db import get_pool
from app.services import auditoria
from app.services.karma import karma_por_carga
from app.services.permisos import exigir

router = APIRouter(tags=["admin"])


class PrecioAdminOut(BaseModel):
    id: UUID
    precio: Decimal
    fecha: datetime
    local_id: UUID
    local_nombre: str
    ean: str | None
    producto_nombre: str | None
    user_id: UUID
    user_alias: str


class PrecioPatch(BaseModel):
    precio: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    motivo: str | None = Field(default=None, max_length=300)


class IdsPrecios(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=MAX_MASIVO)
    motivo: str | None = Field(default=None, max_length=300)
    # Quita al autor el karma que ganó por cada carga borrada (spam, error grosero).
    revertir_karma: bool = False


class OtroPrecioOut(BaseModel):
    id: UUID
    precio: Decimal
    fecha: datetime
    user_alias: str


class PrecioDetalle(PrecioAdminOut):
    """La ficha del precio: con qué se lo puede comparar y quién lo cargó."""

    local_verificado: bool
    user_karma: int
    validaciones: int
    otros_en_el_local: list[OtroPrecioOut]  # mismo producto, mismo local (más nuevos primero)
    promedio_otros_local: Decimal | None
    diferencia_pct: float | None  # contra ese promedio; muy alta = sospechoso
    historial: list[AuditoriaOut]


_SELECT = """
    select p.id, p.precio, p.fecha, p.local_id, l.nombre as local_nombre,
           pc.ean, pc.nombre as producto_nombre, p.user_id, u.alias as user_alias
    from precios p
    join locales l on l.id = p.local_id
    left join productos_canonicos pc on pc.id = p.producto_canonico_id
    join usuarios u on u.id = p.user_id
"""


@router.get("/precios", response_model=Pagina[PrecioAdminOut])
async def listar_precios(
    local_id: UUID | None = None,
    ean: str | None = Query(None, max_length=14),
    user_id: UUID | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: Usuario = Depends(exigir("precio.corregir")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Pagina[PrecioAdminOut]:
    c = Consulta()
    if local_id:
        c.donde("p.local_id = {}", local_id)
    if ean:
        c.donde("pc.ean = {}", ean.strip())
    if user_id:
        c.donde("p.user_id = {}", user_id)
    if desde:
        c.donde("p.fecha >= {}", desde)
    if hasta:
        c.donde("p.fecha < {}::date + 1", hasta)
    total = await pool.fetchval(
        f"""select count(*) from precios p
            left join productos_canonicos pc on pc.id = p.producto_canonico_id {c.where}""",
        *c.args,
    )
    lim, off = c.param(limit), c.param(offset)
    rows = await pool.fetch(
        f"{_SELECT} {c.where} order by p.fecha desc, p.id limit {lim} offset {off}", *c.args
    )
    return Pagina(total=total, items=[PrecioAdminOut(**dict(r)) for r in rows])


@router.get("/precios/{precio_id}", response_model=PrecioDetalle)
async def ficha_precio(
    precio_id: UUID,
    _: Usuario = Depends(exigir("precio.corregir")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> PrecioDetalle:
    row = await pool.fetchrow(
        f"""
        select x.*, l.verificado as local_verificado, u.karma as user_karma,
               (select count(*) from validaciones v where v.precio_id = x.id) as validaciones
        from ({_SELECT} where p.id = $1) x
        join locales l on l.id = x.local_id join usuarios u on u.id = x.user_id
        """,
        precio_id,
    )
    if row is None:
        raise HTTPException(404, "precio no encontrado")
    otros = await pool.fetch(
        """
        select p.id, p.precio, p.fecha, u.alias as user_alias
        from precios p join usuarios u on u.id = p.user_id
        where p.local_id = $1 and p.id <> $2
          and p.producto_canonico_id is not distinct from
              (select producto_canonico_id from precios where id = $2)
        order by p.fecha desc limit 10
        """,
        row["local_id"],
        precio_id,
    )
    promedio = (
        (sum(o["precio"] for o in otros) / len(otros)).quantize(Decimal("0.01")) if otros else None
    )
    dif = float((row["precio"] - promedio) / promedio * 100) if promedio else None
    return PrecioDetalle(
        **dict(row),
        otros_en_el_local=[OtroPrecioOut(**dict(o)) for o in otros],
        promedio_otros_local=promedio,
        diferencia_pct=round(dif, 1) if dif is not None else None,
        historial=await historial(pool, "precio", precio_id),
    )


@router.patch("/precios/{precio_id}", response_model=PrecioAdminOut)
async def corregir_precio(
    precio_id: UUID,
    body: PrecioPatch,
    admin: Usuario = Depends(exigir("precio.corregir")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> PrecioAdminOut:
    """Corrige el monto. La fecha no se toca: la frescura sigue siendo la de la carga."""
    async with pool.acquire() as conn, conn.transaction():
        antes = await conn.fetchval(
            "select precio from precios where id = $1 for update", precio_id
        )
        if antes is None:
            raise HTTPException(404, "precio no encontrado")
        await conn.execute("update precios set precio = $2 where id = $1", precio_id, body.precio)
        await auditoria.registrar(
            conn,
            admin.id,
            "precio.corregir",
            "precio",
            precio_id,
            {"precio": antes},
            {"precio": body.precio},
            nota=body.motivo,
        )
        row = await conn.fetchrow(f"{_SELECT} where p.id = $1", precio_id)
    return PrecioAdminOut(**dict(row))


async def _borrar(
    conn: asyncpg.Connection,
    admin_id: UUID,
    ids: list[UUID],
    motivo: str | None = None,
    revertir_karma: bool = False,
) -> set[UUID]:
    """Borra y deja en la auditoría la fila completa (es el único rastro). El karma que
    ganó el autor por esa carga NO se revierte."""
    hechos: set[UUID] = set()
    for pid in ids:
        antes = await conn.fetchrow(f"{_SELECT} where p.id = $1 for update of p", pid)
        if antes is None:
            continue
        n_val = await conn.fetchval("select count(*) from validaciones where precio_id = $1", pid)
        await conn.execute("delete from validaciones where precio_id = $1", pid)
        await conn.execute("delete from precios where id = $1", pid)
        notas = [motivo] if motivo else []
        if n_val:
            notas.append(f"validaciones borradas: {n_val}")
        if revertir_karma:
            puntos = karma_por_carga()
            # El karma está protegido por trigger: se habilita solo en esta transacción.
            await conn.execute("select set_config('app.karma_write', 'on', true)")
            await conn.execute(
                "update usuarios set karma = greatest(0, karma - $2) where id = $1",
                antes["user_id"],
                puntos,
            )
            notas.append(f"karma revertido: -{puntos}")
        await auditoria.registrar(
            conn, admin_id, "precio.borrar", "precio", pid, antes, nota="; ".join(notas) or None
        )
        hechos.add(pid)
    return hechos


@router.delete("/precios/{precio_id}", status_code=204)
async def borrar_precio(
    precio_id: UUID,
    motivo: str | None = Query(None, max_length=300),
    revertir_karma: bool = False,
    admin: Usuario = Depends(exigir("precio.borrar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> None:
    async with pool.acquire() as conn, conn.transaction():
        if not await _borrar(conn, admin.id, [precio_id], motivo, revertir_karma):
            raise HTTPException(404, "precio no encontrado")


@router.post("/precios/borrar", response_model=ResultadoMasivo)
async def borrar_precios(
    body: IdsPrecios,
    admin: Usuario = Depends(exigir("precio.borrar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ResultadoMasivo:
    ids = list(dict.fromkeys(body.ids))
    async with pool.acquire() as conn, conn.transaction():
        hechos = await _borrar(conn, admin.id, ids, body.motivo, body.revertir_karma)
    return ResultadoMasivo(
        afectados=len(hechos), omitidos=[i for i in ids if i not in hechos], motivo="inexistente"
    )
