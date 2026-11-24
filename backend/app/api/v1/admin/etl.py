"""ETL desde el panel (docs/04 §10-A): definiciones, archivos, cola y cancelación.

El panel arma el formulario con `GET /admin/etl` (la descripción de los parámetros de cada ETL)
y encola con `POST /admin/etl/{clave}/ejecutar`. Las ejecuciones las toma el ejecutor `web`
(subproceso del backend, lo liviano) o el worker `local` (`make etl-worker`, lo pesado): acá
solo se escribe en la cola. Todo `iniciar`/`cancelar`/archivo pasa por `auditoria_admin`.
"""

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.v1.admin.paginas import Pagina
from app.auth import Usuario
from app.db import get_pool
from app.services import auditoria, reglas
from app.services.etl import ParametroInvalido, describir, obtener, todas, validar
from app.services.permisos import exigir

router = APIRouter(tags=["admin"])

MAX_ARCHIVO = 25 * 1024 * 1024  # el mismo tope que el check de `etl_archivos`


async def _error(pool: asyncpg.Pool, codigo: str, **extra: Any) -> HTTPException:
    regla = reglas.REGLAS[codigo]
    return HTTPException(
        regla.status, detail=reglas.detalle(regla, await reglas.mensajes(pool), **extra)
    )


class ParametroOut(BaseModel):
    nombre: str
    tipo: str
    obligatorio: bool
    ayuda: str
    default: Any = None
    opciones: list[str]


class DefinicionOut(BaseModel):
    clave: str
    titulo: str
    descripcion: str
    ejecutor: str
    consume_archivo_con: str | None
    parametros: list[ParametroOut]


class ArchivoOut(BaseModel):
    id: UUID
    nombre: str
    sha256: str
    tamano: int
    creado_en: datetime


class EjecucionResumen(BaseModel):
    id: UUID
    etl: str
    titulo: str | None
    parametros: dict
    estado: str
    ejecutor: str
    creado_por_alias: str | None
    creado_en: datetime
    iniciado_en: datetime | None
    terminado_en: datetime | None
    latido_en: datetime | None
    filas: int | None
    reporte: dict | None
    cancelar: bool


class EjecucionDetalle(EjecucionResumen):
    log: str


class EjecutarIn(BaseModel):
    parametros: dict[str, Any] = Field(default_factory=dict)


_SELECT = """
    select e.id, e.etl, e.parametros::text as parametros, e.estado, e.ejecutor,
           u.alias as creado_por_alias, e.creado_en, e.iniciado_en, e.terminado_en, e.latido_en,
           e.filas, e.reporte::text as reporte, e.cancelar {log}
      from etl_ejecuciones e left join usuarios u on u.id = e.creado_por
"""


def _salida(r: asyncpg.Record, con_log: bool = False) -> EjecucionResumen | EjecucionDetalle:
    d = dict(r)
    d["parametros"] = json.loads(d["parametros"])
    d["reporte"] = json.loads(d["reporte"]) if d["reporte"] else None
    defn = obtener(d["etl"])
    d["titulo"] = defn.titulo if defn else None
    return EjecucionDetalle(**d) if con_log else EjecucionResumen(**d)


@router.get("/etl", response_model=list[DefinicionOut])
async def listar_definiciones(_: Usuario = Depends(exigir("etl.ver"))) -> list[dict]:
    return [describir(d) for d in todas()]


@router.post("/etl/archivos", response_model=ArchivoOut, status_code=201)
async def subir_archivo(
    request: Request,
    nombre: str = Query(..., min_length=1, max_length=200),
    admin: Usuario = Depends(exigir("etl.ejecutar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ArchivoOut:
    """El cuerpo es el archivo crudo (`application/octet-stream`). Se guarda temporalmente en la
    base (docs/04 §10-A) hasta que se importa de verdad o pasan 24 h."""
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > MAX_ARCHIVO:
        raise await _error(pool, "etl_archivo_grande")
    partes: list[bytes] = []
    total = 0
    async for trozo in request.stream():
        total += len(trozo)
        if total > MAX_ARCHIVO:
            raise await _error(pool, "etl_archivo_grande")
        partes.append(trozo)
    if total == 0:
        raise await _error(pool, "etl_archivo_vacio")
    contenido = b"".join(partes)
    sha = hashlib.sha256(contenido).hexdigest()
    async with pool.acquire() as conn, conn.transaction():
        fila = await conn.fetchrow(
            "insert into etl_archivos (nombre, sha256, tamano, contenido, subido_por)"
            " values ($1, $2, $3, $4, $5) returning id, nombre, sha256, tamano, creado_en",
            nombre.strip(),
            sha,
            total,
            contenido,
            admin.id,
        )
        await auditoria.registrar(
            conn, admin.id, "etl.archivo_subir", "etl", fila["id"], None,
            {"nombre": fila["nombre"], "sha256": sha, "tamano": total},
        )  # fmt: skip
    return ArchivoOut(**dict(fila))


@router.delete("/etl/archivos/{archivo_id}", status_code=204)
async def borrar_archivo(
    archivo_id: UUID,
    admin: Usuario = Depends(exigir("etl.ejecutar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> None:
    async with pool.acquire() as conn, conn.transaction():
        fila = await conn.fetchrow(
            "delete from etl_archivos where id = $1 returning nombre, sha256", archivo_id
        )
        if fila is None:
            raise HTTPException(404, "ese archivo no existe (¿ya se borró?)")
        await auditoria.registrar(
            conn, admin.id, "etl.archivo_borrar", "etl", archivo_id, dict(fila), None
        )


@router.post("/etl/{clave}/ejecutar", response_model=EjecucionResumen, status_code=201)
async def ejecutar(
    clave: str,
    body: EjecutarIn,
    admin: Usuario = Depends(exigir("etl.ejecutar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> EjecucionResumen:
    defn = obtener(clave)
    if defn is None:
        raise HTTPException(404, "ese ETL no existe")
    try:
        params = validar(defn, body.parametros)
    except ParametroInvalido as e:
        raise await _error(
            pool, "etl_parametro_invalido", parametro=e.nombre, detalle=e.mensaje
        ) from None
    async with pool.acquire() as conn, conn.transaction():
        for p in defn.parametros:
            if p.tipo != "archivo" or p.nombre not in params:
                continue
            try:
                id_archivo = UUID(params[p.nombre])
            except ValueError:
                raise await _error(pool, "etl_archivo_inexistente", parametro=p.nombre) from None
            meta = await conn.fetchrow(
                "select id, nombre, sha256, tamano from etl_archivos where id = $1", id_archivo
            )
            if meta is None:
                raise await _error(pool, "etl_archivo_inexistente", parametro=p.nombre)
            params[p.nombre] = {k: str(v) for k, v in dict(meta).items()}
        id_ = await conn.fetchval(
            "insert into etl_ejecuciones (etl, parametros, ejecutor, creado_por)"
            " values ($1, $2::jsonb, $3, $4) returning id",
            clave,
            json.dumps(params),
            defn.ejecutor,
            admin.id,
        )
        await auditoria.registrar(
            conn, admin.id, "etl.iniciar", "etl", id_, None,
            {"etl": clave, "ejecutor": defn.ejecutor, "parametros": params},
        )  # fmt: skip
        fila = await conn.fetchrow(_SELECT.format(log="") + " where e.id = $1", id_)
    return _salida(fila)


@router.get("/etl/ejecuciones", response_model=Pagina[EjecucionResumen])
async def listar_ejecuciones(
    etl: str | None = Query(None, max_length=60),
    estado: str | None = Query(None, max_length=20),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: Usuario = Depends(exigir("etl.ver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Pagina[EjecucionResumen]:
    filtros = ("($1::text is null or e.etl = $1)", "($2::text is null or e.estado = $2)")
    donde = " where " + " and ".join(filtros)
    total = await pool.fetchval(f"select count(*) from etl_ejecuciones e{donde}", etl, estado)
    filas = await pool.fetch(
        _SELECT.format(log="") + donde + " order by e.creado_en desc limit $3 offset $4",
        etl, estado, limit, offset,
    )  # fmt: skip
    return Pagina(total=total, items=[_salida(r) for r in filas])


@router.get("/etl/ejecuciones/{ejecucion_id}", response_model=EjecucionDetalle)
async def ver_ejecucion(
    ejecucion_id: UUID,
    _: Usuario = Depends(exigir("etl.ver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> EjecucionDetalle:
    fila = await pool.fetchrow(_SELECT.format(log=", e.log") + " where e.id = $1", ejecucion_id)
    if fila is None:
        raise HTTPException(404, "esa ejecución no existe")
    return _salida(fila, con_log=True)


@router.post("/etl/ejecuciones/{ejecucion_id}/cancelar", response_model=EjecucionResumen)
async def cancelar(
    ejecucion_id: UUID,
    admin: Usuario = Depends(exigir("etl.cancelar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> EjecucionResumen:
    """En cola: se cancela ya. Corriendo: se pide la cancelación y el ejecutor corta el proceso
    en unos segundos (cada lote es una transacción: no quedan datos a medias)."""
    async with pool.acquire() as conn, conn.transaction():
        e = await conn.fetchrow(
            "select estado from etl_ejecuciones where id = $1 for update", ejecucion_id
        )
        if e is None:
            raise HTTPException(404, "esa ejecución no existe")
        if e["estado"] in ("ok", "fallo", "cancelada"):
            raise await _error(pool, "etl_ya_terminada")
        if e["estado"] == "en_cola":
            await conn.execute(
                "update etl_ejecuciones set estado = 'cancelada', terminado_en = now(),"
                " cancelar = true where id = $1",
                ejecucion_id,
            )
        else:
            await conn.execute(
                "update etl_ejecuciones set cancelar = true where id = $1", ejecucion_id
            )
        await auditoria.registrar(
            conn, admin.id, "etl.cancelar", "etl", ejecucion_id, {"estado": e["estado"]}, None
        )
        fila = await conn.fetchrow(_SELECT.format(log="") + " where e.id = $1", ejecucion_id)
    return _salida(fila)
