import json
from datetime import datetime
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.v1.admin.consulta import Consulta
from app.api.v1.admin.paginas import Pagina
from app.auth import Usuario
from app.db import get_pool
from app.services.permisos import exigir

router = APIRouter(tags=["admin"])


class AuditoriaOut(BaseModel):
    id: UUID
    created_at: datetime
    admin_alias: str | None
    accion: str
    entidad: str
    entidad_id: str
    antes: dict | None
    despues: dict | None
    nota: str | None


@router.get("/auditoria", response_model=Pagina[AuditoriaOut])
async def listar_auditoria(
    entidad: str | None = Query(None, max_length=30),
    entidad_id: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: Usuario = Depends(exigir("auditoria.ver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Pagina[AuditoriaOut]:
    c = Consulta()
    if entidad:
        c.donde("a.entidad = {}", entidad)
    if entidad_id:
        c.donde("a.entidad_id = {}", entidad_id)
    total = await pool.fetchval(f"select count(*) from auditoria_admin a {c.where}", *c.args)
    lim, off = c.param(limit), c.param(offset)
    rows = await pool.fetch(
        f"""
        select a.id, a.created_at, u.alias as admin_alias, a.accion, a.entidad, a.entidad_id,
               a.antes::text as antes, a.despues::text as despues, a.nota
        from auditoria_admin a left join usuarios u on u.id = a.usuario_id
        {c.where} order by a.created_at desc, a.id limit {lim} offset {off}
        """,
        *c.args,
    )
    return Pagina(total=total, items=[_a_out(r) for r in rows])


def _a_out(r: asyncpg.Record) -> AuditoriaOut:
    d = dict(r)
    d["antes"] = json.loads(d["antes"]) if d["antes"] else None
    d["despues"] = json.loads(d["despues"]) if d["despues"] else None
    return AuditoriaOut(**d)


async def historial(
    conn: asyncpg.Pool | asyncpg.Connection, entidad: str, entidad_id, limite: int = 15
) -> list[AuditoriaOut]:
    """Últimos cambios de una entidad (para la ficha)."""
    rows = await conn.fetch(
        """
        select a.id, a.created_at, u.alias as admin_alias, a.accion, a.entidad, a.entidad_id,
               a.antes::text as antes, a.despues::text as despues, a.nota
        from auditoria_admin a left join usuarios u on u.id = a.usuario_id
        where a.entidad = $1 and a.entidad_id = $2
        order by a.created_at desc, a.id limit $3
        """,
        entidad,
        str(entidad_id),
        limite,
    )
    return [_a_out(r) for r in rows]
