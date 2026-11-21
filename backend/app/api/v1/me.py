from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from app.auth import Usuario, current_user
from app.db import get_pool
from app.services import dispositivos

router = APIRouter(tags=["me"])


class MeOut(BaseModel):
    id: UUID
    alias: str
    karma: int
    # Moderación (docs/04 §9): la app avisa al cruzar los umbrales.
    escalon: str  # normal | aviso | restringido
    umbral_restriccion: int


@router.get("/me", response_model=MeOut)
async def me(
    user: Usuario = Depends(current_user),
    x_device_id: str | None = Header(default=None),
    pool: asyncpg.Pool = Depends(get_pool),
) -> MeOut:
    # Asocia la cuenta a su celular en cada arranque: las cuentas que ya tenían sesión
    # vigente (sin pasar por el alta ni el refresh) también quedan atadas (docs/04 §9).
    dispositivo = dispositivos.hashear(x_device_id)
    if dispositivo is not None:
        await dispositivos.registrar(pool, dispositivo, user.auth_id)
    return MeOut(
        id=user.id,
        alias=user.alias,
        karma=user.karma,
        escalon=user.escalon,
        umbral_restriccion=user.umbral_restriccion,
    )
