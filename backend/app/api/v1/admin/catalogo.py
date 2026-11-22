"""Productos canónicos y conflictos del ETL (lo que hace `make conflictos`, desde el panel)."""

import json
import re
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field, model_validator

from app.api.v1.admin.auditoria import AuditoriaOut, historial
from app.api.v1.admin.consulta import Consulta, escapar_like
from app.api.v1.admin.paginas import Pagina
from app.api.v1.admin.sugerencias import SugerenciaAdminOut, de_producto
from app.auth import Usuario
from app.db import get_pool
from app.services import auditoria, calidad
from app.services import catalogo as escritura
from app.services.catalogo import Cambios
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
    pack_cantidad: int | None = None
    presentacion: str | None = None
    calidad: int | None = None
    estado_calidad: str | None = None
    calidad_motivos: list[str] = []


ProductoPatch = Cambios  # la corrección directa y la sugerencia dicen lo mismo


class ProductoNuevo(Cambios):
    """Alta simple (Doc 7 §5.1): el EAN y, como mínimo, el nombre."""

    ean: str = Field(pattern="^[0-9]{8,14}$")

    @model_validator(mode="after")
    def _nombre(self):
        if "nombre" not in self.model_fields_set:
            raise ValueError("el nombre es obligatorio")
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
    sugerencias: list[SugerenciaAdminOut] = []


class DesbloquearIn(BaseModel):
    campos: list[str] = Field(min_length=1)
    motivo: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _validar(self):
        malos = set(self.campos) - {"nombre", "marca", "tamano", "presentacion"}
        if malos:
            raise ValueError(f"campos inválidos: {sorted(malos)}")
        return self


class ResolverIn(BaseModel):
    elegido: str = Field(pattern="^(a|b)$")  # a: lo del catálogo; b: lo de la otra fuente


_SELECT_PRODUCTO = """
    select p.id, p.ean, p.nombre, p.marca, p.tamano_valor, p.tamano_unidad, p.origen,
           p.campos_bloqueados, p.pack_cantidad, p.presentacion, p.calidad,
           p.estado_calidad, p.calidad_motivos,
           (select count(*) from conflictos_catalogo c
             where c.ean = p.ean and c.estado = 'pendiente') as conflictos_pendientes
    from productos_canonicos p
"""


@router.get("/productos", response_model=Pagina[ProductoAdminOut])
async def listar_productos(
    q: str | None = Query(None, max_length=100, description="nombre, marca o EAN"),
    origen: str | None = Query(None, pattern="^(off|sepa|manual)$"),
    con_conflictos: bool = False,
    estado: str | None = Query(None, pattern="^(completo|parcial|dudoso|descartado|sin_evaluar)$"),
    motivo: str | None = Query(None, max_length=40, pattern="^[a-z_]+$"),
    orden: str = Query("nombre", pattern="^(nombre|calidad)$"),
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
    if estado == "sin_evaluar":
        c.condiciones.append("p.estado_calidad is null")
    elif estado:
        c.donde("p.estado_calidad = {}", estado)
    if motivo:
        c.donde("{} = any (p.calidad_motivos)", motivo)
    # «Dudosos primero»: dudoso, descartado, parcial, completo; en cada uno, el de menor puntaje.
    ordenar = (
        "case p.estado_calidad when 'dudoso' then 0 when 'descartado' then 1 "
        "when 'parcial' then 2 when 'completo' then 3 else 4 end, p.calidad nulls first, "
        if orden == "calidad"
        else ""
    )
    total = await pool.fetchval(f"select count(*) from productos_canonicos p {c.where}", *c.args)
    lim, off = c.param(limit), c.param(offset)
    rows = await pool.fetch(
        f"{_SELECT_PRODUCTO} {c.where} "
        f"order by {ordenar}lower(p.nombre), p.id limit {lim} offset {off}",
        *c.args,
    )
    return Pagina(total=total, items=[ProductoAdminOut(**dict(r)) for r in rows])


class CalidadResumen(BaseModel):
    total: int
    por_estado: dict[str, int]  # incluye `sin_evaluar`
    por_motivo: dict[str, int]  # motivo -> productos (solo completo/parcial/dudoso/descartado)


@router.get("/catalogo/calidad", response_model=CalidadResumen)
async def tablero_calidad(
    _: Usuario = Depends(exigir("catalogo.editar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> CalidadResumen:
    """Tablero de control (Doc 7 §6): cuántos productos hay por estado y por motivo."""
    estados = await pool.fetch(
        "select coalesce(estado_calidad, 'sin_evaluar') as e, count(*) as n "
        "from productos_canonicos group by 1"
    )
    motivos = await pool.fetch(
        "select m, count(*) as n from productos_canonicos, unnest(calidad_motivos) m "
        "group by m order by n desc"
    )
    por_estado = {e: 0 for e in (*calidad.ESTADOS, "sin_evaluar")}
    por_estado.update({r["e"]: r["n"] for r in estados})
    return CalidadResumen(
        total=sum(por_estado.values()),
        por_estado=por_estado,
        por_motivo={r["m"]: r["n"] for r in motivos},
    )


@router.patch("/productos/{producto_id}", response_model=ProductoAdminOut)
async def corregir_producto(
    producto_id: UUID,
    body: ProductoPatch,
    admin: Usuario = Depends(exigir("catalogo.editar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ProductoAdminOut:
    """Corrige a mano nombre, marca y/o tamaño. Lo corregido queda **bloqueado**: ningún
    ETL lo vuelve a tocar."""
    nuevos = body.a_dict()
    if not nuevos:
        raise HTTPException(422, "no hay nada para cambiar")
    async with pool.acquire() as conn, conn.transaction():
        antes, despues = await escritura.aplicar(conn, producto_id, nuevos)
        if not antes and not despues:
            raise HTTPException(404, "producto no encontrado")
        await auditoria.registrar(
            conn,
            admin.id,
            "producto.corregir",
            "producto",
            producto_id,
            antes,
            despues,
            nota="campos bloqueados: " + ", ".join(escritura.bloqueos(nuevos)),
        )
        row = await conn.fetchrow(f"{_SELECT_PRODUCTO} where p.id = $1", producto_id)
    return ProductoAdminOut(**dict(row))


@router.post("/productos", response_model=ProductoAdminOut, status_code=201)
async def crear_producto(
    body: ProductoNuevo,
    admin: Usuario = Depends(exigir("catalogo.crear")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ProductoAdminOut:
    """Alta simple de un producto que ningún ETL trajo (origen `manual`, todo bloqueado).
    Si el EAN ya existe —aunque esté descartado— se corrige con `PATCH`, no se da de alta."""
    nuevos = body.a_dict()
    async with pool.acquire() as conn, conn.transaction():
        if await conn.fetchval("select 1 from productos_canonicos where ean = $1", body.ean):
            raise HTTPException(409, "ese EAN ya existe: corregilo en vez de darlo de alta")
        producto_id = await escritura.crear(conn, body.ean, nuevos)
        await auditoria.registrar(
            conn,
            admin.id,
            "producto.crear",
            "producto",
            producto_id,
            None,
            {"ean": body.ean, **nuevos},
            nota="alta manual",
        )
        row = await conn.fetchrow(f"{_SELECT_PRODUCTO} where p.id = $1", producto_id)
    return ProductoAdminOut(**dict(row))


@router.get("/catalogo/marcas", response_model=list[str])
async def marcas(
    q: str = Query(..., min_length=1, max_length=50),
    _: Usuario = Depends(exigir("catalogo.editar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[str]:
    """Autocompletado de marca para el formulario: las más usadas que empiezan así."""
    rows = await pool.fetch(
        "select marca from productos_canonicos where lower(marca) like $1 "
        "group by marca order by count(*) desc, marca limit 10",
        f"{escapar_like(q.strip().lower())}%",
    )
    return [r["marca"] for r in rows]


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
        await calidad.recalcular(conn, ean=c["ean"])
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


async def _detalle(pool: asyncpg.Pool, donde: str, valor) -> ProductoDetalle:
    row = await pool.fetchrow(
        f"""
        select x.*, p.imagen_url,
               (select count(*) from precios r where r.producto_canonico_id = x.id) as precios,
               (select count(distinct r.local_id) from precios r
                 where r.producto_canonico_id = x.id) as locales_con_precio
        from ({_SELECT_PRODUCTO} where {donde}) x join productos_canonicos p on p.id = x.id
        """,
        valor,
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
        historial=await historial(pool, "producto", row["id"]),
        sugerencias=await de_producto(pool, row["ean"]),
    )


@router.get("/productos/por-ean/{ean}", response_model=ProductoDetalle)
async def ficha_por_ean(
    ean: str = Path(pattern="^[0-9]{8,14}$"),
    _: Usuario = Depends(exigir("catalogo.editar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ProductoDetalle:
    """«Buscar por EAN» del formulario simple: la ficha, descartado o no. 404 = es un alta."""
    return await _detalle(pool, "p.ean = $1", ean)


@router.get("/productos/{producto_id}", response_model=ProductoDetalle)
async def ficha_producto(
    producto_id: UUID,
    _: Usuario = Depends(exigir("catalogo.editar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ProductoDetalle:
    return await _detalle(pool, "p.id = $1", producto_id)


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
        await calidad.recalcular(conn, producto_id=producto_id)
        row = await conn.fetchrow(f"{_SELECT_PRODUCTO} where p.id = $1", producto_id)
    return ProductoAdminOut(**dict(row))
