"""Productos canónicos y conflictos del ETL (lo que hace `make conflictos`, desde el panel)."""

import json
import re
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from app.api.v1.admin.auditoria import AuditoriaOut, historial
from app.api.v1.admin.consulta import Consulta, escapar_like
from app.api.v1.admin.paginas import Pagina
from app.auth import Usuario
from app.db import get_pool
from app.services import auditoria
from app.services.permisos import exigir

router = APIRouter(tags=["admin"])


class ProductoAdminOut(BaseModel):
    id: UUID
    ean: str
    nombre: str
    marca: str | None
    tamano_valor: Decimal | None
    tamano_unidad: str | None
    origen: str
    campos_bloqueados: list[str]
    conflictos_pendientes: int


class ProductoPatch(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=200)
    marca: str | None = Field(default=None, max_length=100)
    tamano_valor: Decimal | None = Field(default=None, gt=0)
    tamano_unidad: str | None = Field(default=None, pattern="^(g|kg|ml|l|u)$")

    @model_validator(mode="after")
    def _validar(self):
        if "nombre" in self.model_fields_set and (self.nombre is None or not self.nombre.strip()):
            raise ValueError("el nombre no puede estar vacío")
        toca_tamano = {"tamano_valor", "tamano_unidad"} & self.model_fields_set
        if toca_tamano and (self.tamano_valor is None) != (self.tamano_unidad is None):
            raise ValueError("tamaño y unidad van juntos (o los dos vacíos)")
        return self


class ConflictoOut(BaseModel):
    id: UUID
    ean: str
    producto_nombre: str | None
    campo: str
    valor_a: str
    fuente_a: str
    valor_b: str
    fuente_b: str
    estado: str
    elegido: str | None
    created_at: datetime


class FuenteProductoOut(BaseModel):
    fuente: str
    datos: dict  # lo que dijo esa fuente, crudo
    cargado_en: datetime


class ProductoDetalle(ProductoAdminOut):
    """La ficha del producto: qué dijo cada fuente, qué está en disputa y quién lo usa."""

    imagen_url: str | None
    fuentes: list[FuenteProductoOut]
    conflictos: list[ConflictoOut]
    precios: int
    locales_con_precio: int
    historial: list[AuditoriaOut]


class DesbloquearIn(BaseModel):
    campos: list[str] = Field(min_length=1)
    motivo: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _validar(self):
        malos = set(self.campos) - {"nombre", "marca", "tamano"}
        if malos:
            raise ValueError(f"campos inválidos: {sorted(malos)}")
        return self


class ResolverIn(BaseModel):
    elegido: str = Field(pattern="^(a|b)$")  # a: lo del catálogo; b: lo de la otra fuente


_SELECT_PRODUCTO = """
    select p.id, p.ean, p.nombre, p.marca, p.tamano_valor, p.tamano_unidad, p.origen,
           p.campos_bloqueados,
           (select count(*) from conflictos_catalogo c
             where c.ean = p.ean and c.estado = 'pendiente') as conflictos_pendientes
    from productos_canonicos p
"""


@router.get("/productos", response_model=Pagina[ProductoAdminOut])
async def listar_productos(
    q: str | None = Query(None, max_length=100, description="nombre, marca o EAN"),
    origen: str | None = Query(None, pattern="^(off|sepa|manual)$"),
    con_conflictos: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: Usuario = Depends(exigir("catalogo.editar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Pagina[ProductoAdminOut]:
    c = Consulta()
    if origen:
        c.donde("p.origen = {}", origen)
    if q and q.strip():
        t = c.param(f"%{escapar_like(q.strip().lower())}%")
        c.condiciones.append(
            f"(lower(p.nombre) like {t} or lower(coalesce(p.marca, '')) like {t} or p.ean like {t})"
        )
    if con_conflictos:
        c.condiciones.append(
            "exists (select 1 from conflictos_catalogo c "
            "where c.ean = p.ean and c.estado = 'pendiente')"
        )
    total = await pool.fetchval(f"select count(*) from productos_canonicos p {c.where}", *c.args)
    lim, off = c.param(limit), c.param(offset)
    rows = await pool.fetch(
        f"{_SELECT_PRODUCTO} {c.where} order by lower(p.nombre), p.id limit {lim} offset {off}",
        *c.args,
    )
    return Pagina(total=total, items=[ProductoAdminOut(**dict(r)) for r in rows])


@router.patch("/productos/{producto_id}", response_model=ProductoAdminOut)
async def corregir_producto(
    producto_id: UUID,
    body: ProductoPatch,
    admin: Usuario = Depends(exigir("catalogo.editar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ProductoAdminOut:
    """Corrige a mano nombre, marca y/o tamaño. Lo corregido queda **bloqueado**: ningún
    ETL lo vuelve a tocar."""
    async with pool.acquire() as conn, conn.transaction():
        antes = await conn.fetchrow(
            "select nombre, marca, tamano_valor, tamano_unidad from productos_canonicos "
            "where id = $1 for update",
            producto_id,
        )
        if antes is None:
            raise HTTPException(404, "producto no encontrado")
        nuevos: dict = {}
        bloquear: list[str] = []
        for campo in ("nombre", "marca"):
            if campo in body.model_fields_set:
                v = getattr(body, campo)
                nuevos[campo] = v.strip() if v and v.strip() else None
                bloquear.append(campo)
        if {"tamano_valor", "tamano_unidad"} & body.model_fields_set:
            nuevos["tamano_valor"] = body.tamano_valor
            nuevos["tamano_unidad"] = body.tamano_unidad
            bloquear.append("tamano")
        if not nuevos:
            raise HTTPException(422, "no hay nada para cambiar")
        await conn.execute("select set_config('app.catalogo_write', 'on', true)")
        sets = [f"{k} = ${i + 2}" for i, k in enumerate(nuevos)]
        await conn.execute(
            f"update productos_canonicos set {', '.join(sets)}, campos_bloqueados = "
            f"array(select distinct unnest(campos_bloqueados || ${len(nuevos) + 2}::text[])) "
            "where id = $1",
            producto_id,
            *nuevos.values(),
            bloquear,
        )
        await auditoria.registrar(
            conn,
            admin.id,
            "producto.corregir",
            "producto",
            producto_id,
            {k: antes[k] for k in nuevos},
            nuevos,
            nota="campos bloqueados: " + ", ".join(bloquear),
        )
        row = await conn.fetchrow(f"{_SELECT_PRODUCTO} where p.id = $1", producto_id)
    return ProductoAdminOut(**dict(row))


@router.get("/conflictos", response_model=Pagina[ConflictoOut])
async def listar_conflictos(
    estado: str = Query("pendiente", pattern="^(pendiente|resuelto)$"),
    ean: str | None = Query(None, max_length=14),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: Usuario = Depends(exigir("catalogo.resolver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Pagina[ConflictoOut]:
    total = await pool.fetchval(
        "select count(*) from conflictos_catalogo where estado = $1", estado
    )
    rows = await pool.fetch(
        """
        select c.id, c.ean, p.nombre as producto_nombre, c.campo, c.valor_a, c.fuente_a,
               c.valor_b, c.fuente_b, c.estado, c.elegido, c.created_at
        from conflictos_catalogo c left join productos_canonicos p using (ean)
        where c.estado = $1 and ($4::text is null or c.ean = $4)
        order by c.created_at, c.ean limit $2 offset $3
        """,
        estado,
        limit,
        offset,
        ean,
    )
    return Pagina(total=total, items=[ConflictoOut(**dict(r)) for r in rows])


_TAMANO = re.compile(r"^(\d+(?:\.\d+)?) (g|kg|ml|l|u)$")


@router.post("/conflictos/{conflicto_id}/resolver", response_model=ConflictoOut)
async def resolver_conflicto(
    conflicto_id: UUID,
    body: ResolverIn,
    admin: Usuario = Depends(exigir("catalogo.resolver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ConflictoOut:
    """Igual que `make conflictos resolver`: con `b` se pasa el valor de la otra fuente al
    catálogo; en los dos casos el campo queda bloqueado contra el ETL."""
    async with pool.acquire() as conn, conn.transaction():
        c = await conn.fetchrow(
            "select * from conflictos_catalogo where id = $1 for update", conflicto_id
        )
        if c is None:
            raise HTTPException(404, "conflicto no encontrado")
        if c["estado"] != "pendiente":
            raise HTTPException(409, "el conflicto ya estaba resuelto")
        await conn.execute("select set_config('app.catalogo_write', 'on', true)")
        campo = c["campo"]
        if body.elegido == "b":
            if campo == "tamano":
                m = _TAMANO.match(c["valor_b"])
                if m is None:
                    raise HTTPException(422, f"tamaño ilegible: {c['valor_b']!r}")
                await conn.execute(
                    "update productos_canonicos set tamano_valor = $2, tamano_unidad = $3 "
                    "where ean = $1",
                    c["ean"],
                    Decimal(m.group(1)),
                    m.group(2),
                )
            else:
                col = {"nombre": "nombre", "marca": "marca"}[campo]
                await conn.execute(
                    f"update productos_canonicos set {col} = $2 where ean = $1",
                    c["ean"],
                    c["valor_b"],
                )
        await conn.execute(
            "update productos_canonicos set campos_bloqueados = "
            "array(select distinct unnest(campos_bloqueados || $2::text)) where ean = $1",
            c["ean"],
            campo,
        )
        await conn.execute(
            "update conflictos_catalogo set estado = 'resuelto', elegido = $2, "
            "resuelto_por = $3, resuelto_en = now() where id = $1",
            conflicto_id,
            body.elegido,
            admin.id,
        )
        await auditoria.registrar(
            conn,
            admin.id,
            "conflicto.resolver",
            "conflicto",
            conflicto_id,
            {"ean": c["ean"], "campo": campo, "a": c["valor_a"], "b": c["valor_b"]},
            {"elegido": body.elegido},
        )
        row = await conn.fetchrow(
            """
            select c.id, c.ean, p.nombre as producto_nombre, c.campo, c.valor_a, c.fuente_a,
                   c.valor_b, c.fuente_b, c.estado, c.elegido, c.created_at
            from conflictos_catalogo c left join productos_canonicos p using (ean)
            where c.id = $1
            """,
            conflicto_id,
        )
    return ConflictoOut(**dict(row))


@router.get("/productos/{producto_id}", response_model=ProductoDetalle)
async def ficha_producto(
    producto_id: UUID,
    _: Usuario = Depends(exigir("catalogo.editar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ProductoDetalle:
    row = await pool.fetchrow(
        f"""
        select x.*, p.imagen_url,
               (select count(*) from precios r where r.producto_canonico_id = x.id) as precios,
               (select count(distinct r.local_id) from precios r
                 where r.producto_canonico_id = x.id) as locales_con_precio
        from ({_SELECT_PRODUCTO} where p.id = $1) x join productos_canonicos p on p.id = x.id
        """,
        producto_id,
    )
    if row is None:
        raise HTTPException(404, "producto no encontrado")
    fuentes = await pool.fetch(
        "select fuente, datos::text as datos, cargado_en from producto_fuentes "
        "where ean = $1 order by fuente",
        row["ean"],
    )
    conflictos = await pool.fetch(
        """
        select c.id, c.ean, p.nombre as producto_nombre, c.campo, c.valor_a, c.fuente_a,
               c.valor_b, c.fuente_b, c.estado, c.elegido, c.created_at
        from conflictos_catalogo c left join productos_canonicos p using (ean)
        where c.ean = $1 order by c.estado, c.created_at
        """,
        row["ean"],
    )
    return ProductoDetalle(
        **dict(row),
        fuentes=[
            FuenteProductoOut(**{**dict(f), "datos": json.loads(f["datos"])}) for f in fuentes
        ],
        conflictos=[ConflictoOut(**dict(c)) for c in conflictos],
        historial=await historial(pool, "producto", producto_id),
    )


@router.post("/productos/{producto_id}/desbloquear", response_model=ProductoAdminOut)
async def desbloquear_campos(
    producto_id: UUID,
    body: DesbloquearIn,
    admin: Usuario = Depends(exigir("catalogo.editar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ProductoAdminOut:
    """Vuelve a dejar que los ETL toquen esos campos (los habías corregido a mano)."""
    async with pool.acquire() as conn, conn.transaction():
        antes = await conn.fetchval(
            "select campos_bloqueados from productos_canonicos where id = $1 for update",
            producto_id,
        )
        if antes is None:
            raise HTTPException(404, "producto no encontrado")
        sobran = set(body.campos) - set(antes)
        if sobran:
            raise HTTPException(409, f"no estaban bloqueados: {sorted(sobran)}")
        await conn.execute("select set_config('app.catalogo_write', 'on', true)")
        await conn.execute(
            "update productos_canonicos set campos_bloqueados = "
            "array(select c from unnest(campos_bloqueados) c where c <> all($2::text[])) "
            "where id = $1",
            producto_id,
            body.campos,
        )
        await auditoria.registrar(
            conn,
            admin.id,
            "producto.desbloquear",
            "producto",
            producto_id,
            {"campos_bloqueados": antes},
            {"campos_bloqueados": [c for c in antes if c not in body.campos]},
            nota=body.motivo,
        )
        row = await conn.fetchrow(f"{_SELECT_PRODUCTO} where p.id = $1", producto_id)
    return ProductoAdminOut(**dict(row))
