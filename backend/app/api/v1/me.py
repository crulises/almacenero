from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from app.auth import Usuario, current_user
from app.db import get_pool
from app.services import alias, dispositivos

router = APIRouter(tags=["me"])


class MeOut(BaseModel):
    id: UUID
    alias: str
    karma: int
    rol: str  # usuario | moderador | admin (la app muestra «Sugerir» solo al moderador)
    # Moderación (docs/04 §9): la app avisa al cruzar los umbrales.
    escalon: str  # normal | aviso | restringido
    umbral_restriccion: int
    # Alias (config.alias_editable_por_rol): la app muestra el lápiz solo si es true.
    puede_cambiar_alias: bool = False


class AliasIn(BaseModel):
    # El largo fino lo decide el servicio (con mensaje claro); esto solo corta lo absurdo.
    alias: str = Field(max_length=200)


class AliasOut(BaseModel):
    alias: str


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
        rol=user.rol,
        escalon=user.escalon,
        umbral_restriccion=user.umbral_restriccion,
        puede_cambiar_alias=await alias.puede_cambiar(pool, user),
    )


@router.post("/me/alias", response_model=AliasOut)
async def cambiar_alias(
    body: AliasIn,
    user: Usuario = Depends(current_user),
    pool: asyncpg.Pool = Depends(get_pool),
) -> AliasOut:
    """Cambia el alias propio (reglas y quién puede: `services/alias.py`)."""
    return AliasOut(alias=await alias.cambiar_propio(pool, user, body.alias))
