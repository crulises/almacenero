from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import Usuario, current_user
from app.db import get_pool

router = APIRouter(tags=["locales"])


class LocalOut(BaseModel):
    id: UUID
    nombre: str
    direccion: str | None
    lat: float
    lng: float


@router.get("/locales", response_model=list[LocalOut])
async def listar_locales(
    _: Usuario = Depends(current_user), pool: asyncpg.Pool = Depends(get_pool)
) -> list[LocalOut]:
    # v0.0.1: un solo local (el del admin). Alta de locales: fuera de alcance.
    rows = await pool.fetch(
        """
        select id, nombre, direccion,
               st_y(ubicacion::geometry) as lat, st_x(ubicacion::geometry) as lng
        from locales order by created_at
        """
    )
    return [LocalOut(**dict(r)) for r in rows]
