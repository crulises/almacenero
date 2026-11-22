"""Cola de sugerencias de catálogo (docs/04 §10-D): lo que proponen los moderadores.

Aprobar = aplicar los cambios por el mismo camino que la corrección directa del admin
(`services/catalogo.py`: bloquea los campos contra el ETL y recalcula la calidad), auditar y
premiar con karma, todo en una transacción. Rechazar exige una nota.
"""

import json
from datetime import datetime
from uuid import UUID

import asyncpg
import pydantic_core
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.v1.admin.consulta import Consulta, escapar_like
from app.api.v1.admin.paginas import Pagina
from app.auth import Usuario
from app.db import get_pool
from app.services import auditoria, karma, reglas
from app.services import catalogo as escritura
from app.services import config as tunables
from app.services.catalogo import Cambios
from app.services.permisos import exigir

router = APIRouter(tags=["admin"])

ESTADOS = "pendiente|aprobada|rechazada|reemplazada"


class SugerenciaAdminOut(BaseModel):
    id: UUID
    tipo: str  # alta | correccion
    ean: str
    producto_id: UUID | None
    producto_nombre: str | None
    usuario_id: UUID
    usuario_alias: str
    cambios: dict  # lo sugerido
    actual: dict | None  # lo que hay hoy en el catálogo en esos mismos campos
    motivo: str | None
    estado: str
    resuelto_por_alias: str | None
    resuelto_en: datetime | None
    nota_resolucion: str | None
    created_at: datetime


class RechazoIn(BaseModel):
    nota: str = Field(min_length=3, max_length=300)


class AprobacionIn(BaseModel):
    nota: str | None = Field(default=None, max_length=300)


class MasaIn(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=100)
    accion: str = Field(pattern="^(aprobar|rechazar)$")
    nota: str | None = Field(default=None, max_length=300)


class FallaOut(BaseModel):
    id: UUID
    error: str


class MasaOut(BaseModel):
    resueltas: int
    fallidas: list[FallaOut]


SELECT = """
    select s.id, s.ean, s.producto_id, s.usuario_id, s.cambios::text as cambios, s.motivo,
           s.estado, s.resuelto_en, s.nota_resolucion, s.created_at,
           u.alias as usuario_alias, r.alias as resuelto_por_alias,
           p.id as pid, p.nombre, p.marca, p.tamano_valor, p.tamano_unidad,
           p.pack_cantidad, p.presentacion
    from sugerencias_catalogo s
    join usuarios u on u.id = s.usuario_id
    left join usuarios r on r.id = s.resuelto_por
    left join productos_canonicos p on p.ean = s.ean
"""


def salida(r: asyncpg.Record) -> SugerenciaAdminOut:
    cambios = json.loads(r["cambios"])
    existe = r["pid"] is not None
    actual = {k: (str(r[k]) if k == "tamano_valor" and r[k] is not None else r[k]) for k in cambios}
    return SugerenciaAdminOut(
        id=r["id"],
        tipo="correccion" if existe else "alta",
        ean=r["ean"],
        producto_id=r["pid"],
        producto_nombre=r["nombre"],
        usuario_id=r["usuario_id"],
        usuario_alias=r["usuario_alias"],
        cambios=cambios,
        actual=actual if existe else None,
        motivo=r["motivo"],
        estado=r["estado"],
        resuelto_por_alias=r["resuelto_por_alias"],
        resuelto_en=r["resuelto_en"],
        nota_resolucion=r["nota_resolucion"],
        created_at=r["created_at"],
    )


async def de_producto(pool: asyncpg.Pool, ean: str) -> list[SugerenciaAdminOut]:
    rows = await pool.fetch(f"{SELECT} where s.ean = $1 order by s.created_at desc", ean)
    return [salida(r) for r in rows]


@router.get("/sugerencias", response_model=Pagina[SugerenciaAdminOut])
async def listar(
    estado: str = Query("pendiente", pattern=f"^({ESTADOS})$"),
    q: str | None = Query(None, max_length=100, description="EAN, nombre o alias del autor"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: Usuario = Depends(exigir("catalogo.sugerencias.resolver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Pagina[SugerenciaAdminOut]:
    c = Consulta()
    c.donde("s.estado = {}", estado)
    if q and q.strip():
        t = c.param(f"%{escapar_like(q.strip().lower())}%")
        c.condiciones.append(
            f"(s.ean like {t} or lower(coalesce(p.nombre, '')) like {t} "
            f"or lower(s.cambios::text) like {t} or lower(u.alias) like {t})"
        )
    total = await pool.fetchval(
        "select count(*) from sugerencias_catalogo s join usuarios u on u.id = s.usuario_id "
        f"left join productos_canonicos p on p.ean = s.ean {c.where}",
        *c.args,
    )
    lim, off = c.param(limit), c.param(offset)
    rows = await pool.fetch(
        f"{SELECT} {c.where} order by s.created_at, s.id limit {lim} offset {off}", *c.args
    )
    return Pagina(total=total, items=[salida(r) for r in rows])


async def _resolver(
    conn: asyncpg.Connection, admin: Usuario, sugerencia_id: UUID, accion: str, nota: str | None
) -> None:
    """Aprueba o rechaza UNA sugerencia (en la transacción de quien llama)."""
    s = await conn.fetchrow(
        "select id, ean, usuario_id, estado, cambios::text as cambios from sugerencias_catalogo "
        "where id = $1 for update",
        sugerencia_id,
    )
    if s is None:
        raise HTTPException(404, "sugerencia no encontrada")
    if s["estado"] != "pendiente":
        raise HTTPException(409, "la sugerencia ya estaba resuelta")
    if accion == "rechazar":
        if not nota or not nota.strip():
            raise HTTPException(422, "rechazar exige una nota")
        await conn.execute(
            "update sugerencias_catalogo set estado = 'rechazada', resuelto_por = $2, "
            "resuelto_en = now(), nota_resolucion = $3 where id = $1",
            s["id"],
            admin.id,
            nota.strip(),
        )
        await auditoria.registrar(
            conn, admin.id, "sugerencia.rechazar", "sugerencia", s["id"], None, None, nota=nota
        )
        return
    cambios = Cambios(**json.loads(s["cambios"])).a_dict()
    producto_id = await conn.fetchval(
        "select id from productos_canonicos where ean = $1 for update", s["ean"]
    )
    if producto_id is None:  # alta: el producto se crea (origen manual, todo bloqueado)
        if "nombre" not in cambios:
            raise HTTPException(422, "un alta necesita nombre")
        producto_id = await escritura.crear(conn, s["ean"], cambios)
        antes: dict = {}
    else:  # corrección (también un alta cuyo EAN apareció mientras tanto)
        antes, _ = await escritura.aplicar(conn, producto_id, cambios)
    premio = int(await tunables.leer(conn, "karma_sugerencia_aprobada") or 0)
    if premio:
        await karma.sumar_karma(conn, s["usuario_id"], premio)
    await conn.execute(
        "update sugerencias_catalogo set estado = 'aprobada', resuelto_por = $2, "
        "resuelto_en = now(), nota_resolucion = $3, producto_id = $4 where id = $1",
        s["id"],
        admin.id,
        (nota or "").strip() or None,
        producto_id,
    )
    await auditoria.registrar(
        conn,
        admin.id,
        "sugerencia.aprobar",
        "sugerencia",
        s["id"],
        {"ean": s["ean"], **antes},
        cambios,
        nota=f"producto {producto_id}; karma +{premio} al autor",
    )


async def _una(
    pool: asyncpg.Pool, admin: Usuario, sugerencia_id: UUID, accion: str, nota: str | None
) -> SugerenciaAdminOut:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _resolver(conn, admin, sugerencia_id, accion, nota)
        row = await conn.fetchrow(f"{SELECT} where s.id = $1", sugerencia_id)
    return salida(row)


@router.post("/sugerencias/{sugerencia_id}/aprobar", response_model=SugerenciaAdminOut)
async def aprobar(
    sugerencia_id: UUID,
    body: AprobacionIn | None = None,
    admin: Usuario = Depends(exigir("catalogo.sugerencias.resolver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> SugerenciaAdminOut:
    return await _una(pool, admin, sugerencia_id, "aprobar", body.nota if body else None)


@router.post("/sugerencias/{sugerencia_id}/rechazar", response_model=SugerenciaAdminOut)
async def rechazar(
    sugerencia_id: UUID,
    body: RechazoIn,
    admin: Usuario = Depends(exigir("catalogo.sugerencias.resolver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> SugerenciaAdminOut:
    return await _una(pool, admin, sugerencia_id, "rechazar", body.nota)


@router.post("/sugerencias/resolver", response_model=MasaOut)
async def resolver_en_masa(
    body: MasaIn,
    admin: Usuario = Depends(exigir("catalogo.sugerencias.resolver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> MasaOut:
    """Aprueba o rechaza varias a la vez. Cada una va en su propia transacción: si una falla
    (ya resuelta, EAN inválido…) las demás igual se resuelven y la falla se informa."""
    if body.accion == "rechazar" and not (body.nota and body.nota.strip()):
        raise HTTPException(422, "rechazar exige una nota")
    resueltas, fallidas = 0, []
    for sid in dict.fromkeys(body.ids):
        try:
            await _una(pool, admin, sid, body.accion, body.nota)
            resueltas += 1
        except HTTPException as e:
            fallidas.append(FallaOut(id=sid, error=str(e.detail)))
        except (asyncpg.PostgresError, pydantic_core.ValidationError) as e:
            texto = await reglas.explicar(pool, e)
            fallidas.append(FallaOut(id=sid, error=texto))
    return MasaOut(resueltas=resueltas, fallidas=fallidas)
