"""Dashboard de admin (docs/04 §11, corte 19a): `/v1/admin/dashboard/...`.

Solo lectura y solo admin (`dashboard.ver`). Los datos de usuarios muestran alias, nunca email.
Los instantes salen en UTC (ISO-8601 con Z); la zona del panel decide cómo se agrupan (§11.3).
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import Usuario
from app.db import get_pool
from app.services import dashboard, reglas
from app.services.permisos import exigir

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

Granularidad = Literal["hora", "dia", "semana", "mes"]


async def _error(pool: asyncpg.Pool, codigo: str, **extra: Any) -> HTTPException:
    regla = reglas.REGLAS[codigo]
    return HTTPException(
        regla.status, detail=reglas.detalle(regla, await reglas.mensajes(pool), **extra)
    )


async def _periodo(
    pool: asyncpg.Pool, desde: datetime | None, hasta: datetime | None, dias: int = 7
) -> dashboard.Periodo:
    try:
        return dashboard.periodo(desde, hasta, dias)
    except dashboard.PeriodoInvalido as e:
        raise await _error(pool, "periodo_invalido", detalle=str(e)) from None


async def _zona(pool: asyncpg.Pool, pedida: str | None) -> str:
    try:
        return await dashboard.zona_del_panel(pool, pedida)
    except dashboard.ZonaInvalida as e:
        raise await _error(pool, "zona_invalida", zona=str(e)) from None


class Cantidad(BaseModel):
    periodo: int
    total: int


class UsuariosActivos(BaseModel):
    dias: int
    anonimos: int
    registrados: int


class InvitacionesResumen(BaseModel):
    emitidas: int
    disponibles: int
    usadas: int
    vencidas: int
    aceptadas_periodo: int
    aceptadas_total: int


class EventosEstado(BaseModel):
    total: int
    max_filas: int
    superado: bool  # el dashboard avisa y ofrece exportar (docs/04 §11.4)


class ResumenOut(BaseModel):
    eventos: EventosEstado
    desde: datetime
    hasta: datetime
    zona: str
    precios: Cantidad
    validaciones: Cantidad
    usuarios_activos: UsuariosActivos
    invitaciones: InvitacionesResumen


@router.get("/resumen", response_model=ResumenOut)
async def resumen(
    desde: datetime | None = None,
    hasta: datetime | None = None,
    zona: str | None = Query(None, max_length=64),
    _: Usuario = Depends(exigir("dashboard.ver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ResumenOut:
    p = await _periodo(pool, desde, hasta)
    z = await _zona(pool, zona)
    return ResumenOut(desde=p.desde, hasta=p.hasta, zona=z, **await dashboard.resumen(pool, p))


class Punto(BaseModel):
    inicio_utc: datetime
    valor: int
    anonimos: int | None = None  # solo en `activos`
    registrados: int | None = None


class SerieOut(BaseModel):
    metrica: str
    granularidad: str
    zona: str
    desde: datetime
    hasta: datetime
    puntos: list[Punto]


@router.get("/series", response_model=SerieOut)
async def series(
    metrica: Literal["precios", "validaciones", "activos", "invitaciones"] = "precios",
    granularidad: Granularidad = "dia",
    desde: datetime | None = None,
    hasta: datetime | None = None,
    zona: str | None = Query(None, max_length=64),
    _: Usuario = Depends(exigir("dashboard.ver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> SerieOut:
    p = await _periodo(pool, desde, hasta)
    z = await _zona(pool, zona)
    try:
        puntos = await dashboard.serie(pool, metrica, granularidad, p, z)
    except dashboard.PeriodoInvalido as e:
        raise await _error(pool, "periodo_invalido", detalle=str(e)) from None
    return SerieOut(
        metrica=metrica,
        granularidad=granularidad,
        zona=z,
        desde=p.desde,
        hasta=p.hasta,
        puntos=[Punto(**x) for x in puntos],
    )


class RankingItem(BaseModel):
    id: UUID
    alias: str
    rol: str
    es_anonimo: bool
    cantidad: int


@router.get("/rankings", response_model=list[RankingItem])
async def rankings(
    tipo: Literal["productos", "precios", "sugerencias"] = "precios",
    desde: datetime | None = None,
    hasta: datetime | None = None,
    limite: int = Query(10, ge=1, le=50),
    _: Usuario = Depends(exigir("dashboard.ver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[RankingItem]:
    p = await _periodo(pool, desde, hasta, 30)
    return [RankingItem(**r) for r in await dashboard.ranking(pool, tipo, p, limite)]


class Estrella(BaseModel):
    ean: str
    nombre: str | None
    marca: str | None
    usuarios: int
    escaneos: int
    encontrado: bool | None


@router.get("/estrellas", response_model=list[Estrella])
async def estrellas(
    desde: datetime | None = None,
    hasta: datetime | None = None,
    via: Literal["camara", "manual"] | None = None,
    limite: int = Query(10, ge=1, le=50),
    _: Usuario = Depends(exigir("dashboard.ver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[Estrella]:
    p = await _periodo(pool, desde, hasta, 30)
    return [Estrella(**r) for r in await dashboard.estrellas(pool, p, limite, via)]


@router.get("/zonas")
async def zonas(
    desde: datetime | None = None,
    hasta: datetime | None = None,
    _: Usuario = Depends(exigir("dashboard.ver")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """GeoJSON de celdas con la cantidad de precios cargados (mapa de zonas con más actividad)."""
    p = await _periodo(pool, desde, hasta, 30)
    return await dashboard.zonas(pool, p)
