"""Programación de ETL, almacén de exportaciones y exportaciones de eventos (docs/04 §11.4).

- `/etl/programaciones`: CRUD de las programaciones (cron en UTC; el panel muestra hora local).
- `/almacen/probar`: ida y vuelta con un archivo de prueba, antes de activar una programación.
- `/eventos/exportaciones`: lista de lo exportado y descarga desde el almacén.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.auth import Usuario
from app.db import get_pool
from app.services import auditoria, cron, reglas
from app.services.etl import ParametroInvalido, obtener, validar
from app.services.permisos import exigir

router = APIRouter(tags=["admin"])


async def _error(pool: asyncpg.Pool, codigo: str, **extra: Any) -> HTTPException:
    regla = reglas.REGLAS[codigo]
    return HTTPException(
        regla.status, detail=reglas.detalle(regla, await reglas.mensajes(pool), **extra)
    )


class ProgramacionOut(BaseModel):
    id: UUID
    etl: str
    titulo: str | None
    parametros: dict
    cron: str
    activa: bool
    al_superar_umbral: bool
    ultima_corrida: datetime | None
    proxima_corrida: datetime | None
    ultima_ejecucion_id: UUID | None
    ultima_estado: str | None
    creado_en: datetime


class ProgramacionIn(BaseModel):
    etl: str = Field(max_length=100)
    parametros: dict[str, Any] = Field(default_factory=dict)
    cron: str = Field(max_length=100)
    activa: bool = False
    al_superar_umbral: bool = False


class ProgramacionPatch(BaseModel):
    parametros: dict[str, Any] | None = None
    cron: str | None = Field(default=None, max_length=100)
    activa: bool | None = None
    al_superar_umbral: bool | None = None


_SELECT = """
    select p.id, p.etl, p.parametros::text as parametros, p.cron, p.activa, p.al_superar_umbral,
           p.ultima_corrida, p.proxima_corrida, p.ultima_ejecucion_id, e.estado as ultima_estado,
           p.creado_en
      from etl_programaciones p left join etl_ejecuciones e on e.id = p.ultima_ejecucion_id
"""


def _out(r: asyncpg.Record) -> ProgramacionOut:
    d = dict(r)
    d["parametros"] = json.loads(d["parametros"])
    defn = obtener(d["etl"])
    d["titulo"] = defn.titulo if defn else None
    return ProgramacionOut(**d)


async def _validar(
    pool: asyncpg.Pool, etl: str, parametros: dict, texto_cron: str | None, umbral: bool
) -> tuple[dict, datetime | None]:
    defn = obtener(etl)
    if defn is None:
        raise HTTPException(404, "ese ETL no existe")
    if any(p.tipo == "archivo" for p in defn.parametros):
        raise HTTPException(422, "un ETL que necesita subir un archivo no se puede programar")
    try:
        params = validar(defn, parametros)
    except ParametroInvalido as e:
        raise await _error(
            pool, "etl_parametro_invalido", parametro=e.nombre, detalle=e.mensaje
        ) from None
    if umbral and etl != "eventos_exportar":
        raise HTTPException(422, "«al superar el umbral» solo existe para eventos_exportar")
    proxima = None
    if texto_cron is not None:
        try:
            proxima = cron.proxima(texto_cron, datetime.now(timezone.utc))
        except cron.CronInvalido as e:
            raise await _error(pool, "cron_invalido", detalle=str(e)) from None
    return params, proxima


@router.get("/etl/programaciones", response_model=list[ProgramacionOut])
async def listar_programaciones(
    _: Usuario = Depends(exigir("etl.ver")), pool: asyncpg.Pool = Depends(get_pool)
) -> list[ProgramacionOut]:
    rows = await pool.fetch(_SELECT + " order by p.creado_en")
    return [_out(r) for r in rows]


@router.post("/etl/programaciones", response_model=ProgramacionOut, status_code=201)
async def crear_programacion(
    body: ProgramacionIn,
    admin: Usuario = Depends(exigir("etl.programar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ProgramacionOut:
    params, proxima = await _validar(
        pool, body.etl, body.parametros, body.cron, body.al_superar_umbral
    )
    async with pool.acquire() as conn, conn.transaction():
        id_ = await conn.fetchval(
            "insert into etl_programaciones (etl, parametros, cron, activa, al_superar_umbral, "
            "proxima_corrida, creado_por) values ($1, $2::jsonb, $3, $4, $5, $6, $7) returning id",
            body.etl,
            json.dumps(params),
            body.cron.strip(),
            body.activa,
            body.al_superar_umbral,
            proxima,
            admin.id,
        )
        await auditoria.registrar(
            conn, admin.id, "programacion.crear", "etl", id_, None,
            {**body.model_dump(), "parametros": params},
        )  # fmt: skip
        fila = await conn.fetchrow(_SELECT + " where p.id = $1", id_)
    return _out(fila)


@router.patch("/etl/programaciones/{id_}", response_model=ProgramacionOut)
async def cambiar_programacion(
    id_: UUID,
    body: ProgramacionPatch,
    admin: Usuario = Depends(exigir("etl.programar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ProgramacionOut:
    async with pool.acquire() as conn, conn.transaction():
        previa = await conn.fetchrow(
            "select * from etl_programaciones where id = $1 for update", id_
        )
        if previa is None:
            raise await _error(pool, "programacion_inexistente")
        cambios = body.model_dump(exclude_unset=True)
        texto = cambios.get("cron", previa["cron"]).strip()
        parametros = cambios.get("parametros", json.loads(previa["parametros"]))
        umbral = cambios.get("al_superar_umbral", previa["al_superar_umbral"])
        activa = cambios.get("activa", previa["activa"])
        params, proxima = await _validar(pool, previa["etl"], parametros, texto, umbral)
        await conn.execute(
            "update etl_programaciones set parametros = $2::jsonb, cron = $3, activa = $4, "
            "al_superar_umbral = $5, proxima_corrida = $6 where id = $1",
            id_, json.dumps(params), texto, activa, umbral, proxima,
        )  # fmt: skip
        await auditoria.registrar(
            conn, admin.id, "programacion.cambiar", "etl", id_,
            {"cron": previa["cron"], "activa": previa["activa"],
             "parametros": json.loads(previa["parametros"])},
            {"cron": texto, "activa": activa, "parametros": params},
        )  # fmt: skip
        fila = await conn.fetchrow(_SELECT + " where p.id = $1", id_)
    return _out(fila)


@router.delete("/etl/programaciones/{id_}", status_code=204)
async def borrar_programacion(
    id_: UUID,
    admin: Usuario = Depends(exigir("etl.programar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Response:
    async with pool.acquire() as conn, conn.transaction():
        previa = await conn.fetchrow("select etl, cron from etl_programaciones where id = $1", id_)
        if previa is None:
            raise await _error(pool, "programacion_inexistente")
        await conn.execute("delete from etl_programaciones where id = $1", id_)
        await auditoria.registrar(
            conn, admin.id, "programacion.borrar", "etl", id_, dict(previa), None
        )
    return Response(status_code=204)


# ------------------------------------------------------------------ almacén
def _almacen():
    from etl.comun import almacen

    return almacen


@router.post("/almacen/probar")
async def probar_almacen(
    admin: Usuario = Depends(exigir("etl.programar")), pool: asyncpg.Pool = Depends(get_pool)
) -> dict:
    """Ida y vuelta con un archivo de prueba (sube, relee, compara tamaño y sha256, borra)."""
    almacen = _almacen()
    try:
        alm = await asyncio.to_thread(almacen.desde_entorno)
        r = await asyncio.to_thread(almacen.probar, alm)
    except Exception as e:  # noqa: BLE001 - cualquier falla de configuración o de red
        raise await _error(pool, "almacen_fallo", detalle=str(e)) from None
    async with pool.acquire() as conn:
        await auditoria.registrar(conn, admin.id, "almacen.probar", "etl", r["almacen"], None, r)
    return r


# ------------------------------------------------------ exportaciones de eventos
class ExportacionOut(BaseModel):
    id: UUID
    tipo: str | None
    id_desde: int
    id_hasta: int
    filas: int
    sha256: str
    tamano: int
    clave: str
    almacen: str
    borradas: int
    creado_en: datetime


@router.get("/eventos/exportaciones", response_model=list[ExportacionOut])
async def listar_exportaciones(
    _: Usuario = Depends(exigir("etl.ver")), pool: asyncpg.Pool = Depends(get_pool)
) -> list[ExportacionOut]:
    rows = await pool.fetch(
        "select id, tipo, id_desde, id_hasta, filas, sha256, tamano, clave, almacen, borradas, "
        "creado_en from eventos_exportaciones order by creado_en desc, id_desde desc limit 200"
    )
    return [ExportacionOut(**dict(r)) for r in rows]


@router.get("/eventos/exportaciones/{id_}/descargar")
async def descargar_exportacion(
    id_: UUID,
    admin: Usuario = Depends(exigir("etl.ejecutar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> Response:
    fila = await pool.fetchrow("select clave, sha256 from eventos_exportaciones where id = $1", id_)
    if fila is None:
        raise await _error(pool, "exportacion_inexistente")
    almacen = _almacen()
    try:
        alm = await asyncio.to_thread(almacen.desde_entorno)
        datos = await asyncio.to_thread(alm.leer, fila["clave"])
    except Exception:  # noqa: BLE001
        raise await _error(pool, "exportacion_inexistente") from None
    async with pool.acquire() as conn:
        await auditoria.registrar(
            conn,
            admin.id,
            "eventos.descargar_exportacion",
            "etl",
            id_,
            None,
            {"clave": fila["clave"]},
        )
    nombre = fila["clave"].rsplit("/", 1)[-1]
    return Response(
        datos,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre}"',
            "X-Sha256": fila["sha256"],
        },
    )
