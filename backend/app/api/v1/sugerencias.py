"""Sugerencias de catálogo del moderador (docs/04 §10-D): propone una corrección o un alta.

No toca el catálogo: queda en la cola `sugerencias_catalogo` hasta que un admin la aprueba
(`/v1/admin/sugerencias`). Para proponer hace falta la capacidad `catalogo.sugerir`, que un
moderador pierde si su karma lo restringe (como cualquier otra carga).
"""

import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import Usuario
from app.db import get_pool
from app.services import auditoria
from app.services.catalogo import CAMPOS, Cambios
from app.services.permisos import exigir

router = APIRouter(prefix="/catalogo/sugerencias", tags=["catalogo"])


class SugerenciaIn(Cambios):
    """Los mismos campos que una corrección directa, más el EAN y el porqué."""

    ean: str = Field(pattern="^[0-9]{8,14}$")
    motivo: str | None = Field(default=None, max_length=300)


class SugerenciaOut(BaseModel):
    id: UUID
    ean: str
    tipo: str  # alta | correccion
    cambios: dict
    motivo: str | None
    estado: str
    nota_resolucion: str | None
    created_at: datetime
    resuelto_en: datetime | None


_SELECT = """
    select s.id, s.ean, s.cambios::text as cambios, s.motivo, s.estado, s.nota_resolucion,
           s.created_at, s.resuelto_en, (p.id is not null) as existe
    from sugerencias_catalogo s left join productos_canonicos p on p.ean = s.ean
"""


def _salida(r: asyncpg.Record) -> SugerenciaOut:
    return SugerenciaOut(
        id=r["id"],
        ean=r["ean"],
        tipo="correccion" if r["existe"] else "alta",
        cambios=json.loads(r["cambios"]),
        motivo=r["motivo"],
        estado=r["estado"],
        nota_resolucion=r["nota_resolucion"],
        created_at=r["created_at"],
        resuelto_en=r["resuelto_en"],
    )


@router.post("", response_model=SugerenciaOut, status_code=201)
async def sugerir(
    body: SugerenciaIn,
    user: Usuario = Depends(exigir("catalogo.sugerir")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> SugerenciaOut:
    """Propone cambios para un EAN. Si el producto existe (aunque esté descartado) es una
    corrección y solo cuentan los campos que de verdad cambian; si no existe, es un alta y
    hace falta al menos el nombre. Una sugerencia nueva reemplaza a la pendiente anterior
    del mismo autor para ese EAN."""
    cambios = body.a_dict()
    if not cambios:
        raise HTTPException(422, "no sugerís ningún cambio")
    async with pool.acquire() as conn, conn.transaction():
        actual = await conn.fetchrow(
            f"select id, {', '.join(CAMPOS)} from productos_canonicos where ean = $1", body.ean
        )
        if actual is None:
            if "nombre" not in cambios:
                raise HTTPException(422, "para dar de alta un producto hace falta el nombre")
        else:
            cambios = {k: v for k, v in cambios.items() if _distinto(actual[k], v)}
            if not cambios:
                raise HTTPException(422, "eso ya es lo que dice el catálogo")
        await conn.execute(
            "update sugerencias_catalogo set estado = 'reemplazada', resuelto_en = now() "
            "where ean = $1 and usuario_id = $2 and estado = 'pendiente'",
            body.ean,
            user.id,
        )
        row = await conn.fetchrow(
            "insert into sugerencias_catalogo (producto_id, ean, usuario_id, cambios, motivo) "
            "values ($1, $2, $3, $4::jsonb, $5) returning id",
            actual["id"] if actual else None,
            body.ean,
            user.id,
            auditoria.a_json(cambios),
            body.motivo.strip() if body.motivo and body.motivo.strip() else None,
        )
        out = await conn.fetchrow(f"{_SELECT} where s.id = $1", row["id"])
    return _salida(out)


def _distinto(actual, nuevo) -> bool:
    if isinstance(actual, Decimal) and nuevo is not None:
        return actual != Decimal(str(nuevo))
    return actual != nuevo


@router.get("/mias", response_model=list[SugerenciaOut])
async def mis_sugerencias(
    estado: str | None = Query(None, pattern="^(pendiente|aprobada|rechazada|reemplazada)$"),
    limit: int = Query(50, ge=1, le=100),
    user: Usuario = Depends(exigir("catalogo.sugerir")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[SugerenciaOut]:
    rows = await pool.fetch(
        f"{_SELECT} where s.usuario_id = $1 and ($2::text is null or s.estado = $2) "
        "order by s.created_at desc limit $3",
        user.id,
        estado,
        limit,
    )
    return [_salida(r) for r in rows]
