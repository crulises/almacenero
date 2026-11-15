import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.api.v1 import router as v1_router
from app.config import get_settings
from app.db import create_pool
from app.logging import setup_logging

log = logging.getLogger("almacenero")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(get_settings().log_level)
    app.state.pool = await create_pool()
    app.state.http = httpx.AsyncClient()
    log.info("backend iniciado")
    try:
        yield
    finally:
        await app.state.http.aclose()
        await app.state.pool.close()


app = FastAPI(title="Almacenero API", version="0.0.1", lifespan=lifespan)
app.include_router(v1_router)
