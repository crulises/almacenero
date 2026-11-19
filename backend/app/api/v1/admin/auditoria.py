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
    items = []
    for r in rows:
        d = dict(r)
        d["antes"] = json.loads(d["antes"]) if d["antes"] else None
        d["despues"] = json.loads(d["despues"]) if d["despues"] else None
        items.append(AuditoriaOut(**d))
    return Pagina(total=total, items=items)
