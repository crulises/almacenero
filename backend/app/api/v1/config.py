import json

import asyncpg
from fastapi import APIRouter, Depends

from app.db import get_pool

router = APIRouter(tags=["config"])


@router.get("/config")
async def get_config(pool: asyncpg.Pool = Depends(get_pool)) -> list[dict]:
    """Tunables de admin. La app los lee al arrancar y los cachea."""
    rows = await pool.fetch("select clave, valor::text as valor, rubro from config order by clave")
    return [
        {"clave": r["clave"], "valor": json.loads(r["valor"]), "rubro": r["rubro"]} for r in rows
    ]
