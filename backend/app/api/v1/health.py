import asyncpg
from fastapi import APIRouter, Depends

from app.db import get_pool

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    await pool.fetchval("select 1")
    return {"status": "ok"}
