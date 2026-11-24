from datetime import datetime

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.auth import Usuario, current_user
from app.db import get_pool
from app.services import config, eventos, reglas
from app.services.ratelimit import limitar

router = APIRouter(tags=["eventos"])


class EventoIn(BaseModel):
    tipo: str = Field(max_length=100)
    datos: dict = Field(default_factory=dict)
    # El reloj del celular: solo se guarda dentro de `datos`, nunca agrupa (docs/04 §11.2).
    ocurrio_en_cliente: datetime | None = None


class LoteIn(BaseModel):
    eventos: list[EventoIn] = Field(max_length=eventos.MAX_POR_LOTE)


class LoteGuardado(BaseModel):
    guardados: int


@router.post("/eventos", response_model=LoteGuardado, status_code=201)
async def registrar_eventos(
    body: LoteIn,
    user: Usuario = Depends(current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> LoteGuardado:
    """Recibe hasta 50 eventos juntos (la app los junta para no gastar batería). Todo o nada:
    si uno no es válido no se guarda ninguno, y la respuesta dice cuál y qué regla."""
    limitar(
        f"eventos:{user.id}",
        int(await config.leer(pool, "max_lotes_eventos_por_hora")),
        3600,
        "mandaste demasiados eventos juntos: probá más tarde",
    )
    editados = await reglas.mensajes(pool)
    listos: list[eventos.EventoListo] = []
    for i, e in enumerate(body.eventos):
        tipo = eventos.tipo_aceptado(e.tipo)
        if tipo is None:
            raise HTTPException(
                400,
                detail=reglas.detalle(
                    reglas.REGLAS["evento_tipo_desconocido"], editados, indice=i, tipo=e.tipo
                ),
            )
        try:
            listos.append(eventos.preparar(tipo, e.tipo, e.datos, e.ocurrio_en_cliente))
        except ValidationError as exc:
            problemas = reglas.problemas(exc)
            raise HTTPException(
                422,
                detail=reglas.detalle(
                    reglas.REGLAS["evento_datos_invalidos"],
                    editados,
                    indice=i,
                    tipo=e.tipo,
                    campos=problemas,
                ),
            ) from exc
    async with pool.acquire() as conn, conn.transaction():
        n = await eventos.guardar(conn, user.id, listos)
    return LoteGuardado(guardados=n)
