"""Invitaciones y PINs de un solo uso desde el panel (docs/04, §6).

Un PIN es una invitación con `usos_max = 1`. El estado se CALCULA, no se guarda:
- `usada`: `usos >= usos_max` (un PIN, una persona, una vez).
- `vencida`: sin usar y con `vence` en el pasado.
- `disponible`: el resto (incluye los códigos compartidos sin tope de usos).
"""

from datetime import datetime
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.api.v1.admin.paginas import Pagina
from app.auth import Usuario
from app.db import get_pool
from app.services import auditoria, invitaciones
from app.services.permisos import exigir

router = APIRouter(tags=["admin"])

# Misma definición en el SELECT y en el filtro: un solo lugar.
_ESTADO = """
    case
        when i.usos_max is not null and i.usos >= i.usos_max then 'usada'
        when i.vence is not null and i.vence <= now() then 'vencida'
        else 'disponible'
    end
"""

_SELECT = f"""
    select i.id, i.codigo, i.nota, i.usos, i.usos_max, i.vence, i.created_at, i.usada_at,
           {_ESTADO} as estado,
           u.id as usada_por_id, u.alias as usada_por_alias,
           coalesce(u.estado = 'baja', false) as usada_por_baja,
           c.alias as creada_por_alias
    from invitaciones i
    left join usuarios u on u.auth_id = i.usada_por_auth
    left join usuarios c on c.id = i.creada_por
"""


class InvitacionOut(BaseModel):
    id: UUID
    codigo: str
    nota: str | None
    estado: str  # disponible | usada | vencida
    usos: int
    usos_max: int | None
    vence: datetime | None
    created_at: datetime
    usada_at: datetime | None
    usada_por_id: UUID | None  # para abrir la ficha del usuario
    usada_por_alias: str | None
    usada_por_baja: bool  # quien entró con este código está dado de baja
    creada_por_alias: str | None


class PinesIn(BaseModel):
    cantidad: int = Field(default=1, ge=1, le=invitaciones.MAX_LOTE)
    # Se aplica a cada PIN del lote: «Juan», «Cumple de Ana», etc.
    nota: str | None = Field(default=None, max_length=200)
    # Cuánto dura sin usarse. Sin valor, no vence. Hasta un año.
    vigencia_horas: int | None = Field(default=24, ge=1, le=24 * 365)

    @field_validator("nota")
    @classmethod
    def _recortar(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v else None


@router.get("/invitaciones", response_model=Pagina[InvitacionOut])
async def listar_invitaciones(
    estado: str | None = Query(None, pattern="^(disponible|usada|vencida)$"),
    q: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: Usuario = Depends(exigir("invitacion.ver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Pagina[InvitacionOut]:
    cond, args = [], []
    if estado:
        args.append(estado)
        cond.append(f"({_ESTADO}) = ${len(args)}")
    if q:
        args.append(f"%{q.strip()}%")
        cond.append(f"(i.codigo ilike ${len(args)} or i.nota ilike ${len(args)})")
    donde = f"where {' and '.join(cond)}" if cond else ""
    total = await pool.fetchval(f"select count(*) from invitaciones i {donde}", *args)
    rows = await pool.fetch(
        f"{_SELECT} {donde} order by i.created_at desc, i.codigo "
        f"limit ${len(args) + 1} offset ${len(args) + 2}",
        *args,
        limit,
        offset,
    )
    return Pagina(total=total, items=[InvitacionOut(**dict(r)) for r in rows])


@router.post("/invitaciones", response_model=list[InvitacionOut], status_code=201)
async def crear_pines(
    body: PinesIn,
    admin: Usuario = Depends(exigir("invitacion.emitir")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[InvitacionOut]:
    """Crea `cantidad` PINs de 6 dígitos, de un solo uso. Quedan registrados uno por
    uno en la auditoría."""
    async with pool.acquire() as conn, conn.transaction():
        try:
            nuevos = await invitaciones.crear_pines(
                conn, body.cantidad, body.nota, body.vigencia_horas, admin.id
            )
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from e
        for n in nuevos:
            await auditoria.registrar(
                conn,
                admin.id,
                "invitacion.crear",
                "invitacion",
                n["id"],
                despues={"codigo": n["codigo"], "nota": n["nota"], "vence": n["vence"]},
            )
        rows = await conn.fetch(
            f"{_SELECT} where i.id = any($1::uuid[]) order by i.created_at, i.codigo",
            [n["id"] for n in nuevos],
        )
    return [InvitacionOut(**dict(r)) for r in rows]


@router.delete("/invitaciones/{invitacion_id}", status_code=204)
async def revocar_invitacion(
    invitacion_id: UUID,
    admin: Usuario = Depends(exigir("invitacion.emitir")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> None:
    """Anula una invitación que todavía no se usó. Una usada no se borra: queda como
    registro de quién entró con ella."""
    async with pool.acquire() as conn, conn.transaction():
        previa = await conn.fetchrow(
            "select codigo, nota, usos from invitaciones where id = $1 for update",
            invitacion_id,
        )
        if previa is None:
            raise HTTPException(404, "invitación no encontrada")
        if previa["usos"] > 0:
            raise HTTPException(409, "ya se usó: queda como registro, no se puede borrar")
        await conn.execute("delete from invitaciones where id = $1", invitacion_id)
        await auditoria.registrar(
            conn,
            admin.id,
            "invitacion.revocar",
            "invitacion",
            invitacion_id,
            antes={"codigo": previa["codigo"], "nota": previa["nota"]},
        )
