from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import Usuario, current_user

router = APIRouter(tags=["me"])


class MeOut(BaseModel):
    id: UUID
    alias: str
    karma: int


@router.get("/me", response_model=MeOut)
async def me(user: Usuario = Depends(current_user)) -> MeOut:
    return MeOut(id=user.id, alias=user.alias, karma=user.karma)
