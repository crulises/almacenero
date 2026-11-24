import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import errores
from app.api.v1 import router as v1_router
from app.config import get_settings
from app.db import create_pool
from app.logging import setup_logging
from app.services.etl import EjecutorWeb

log = logging.getLogger("almacenero")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(get_settings().log_level)
    app.state.pool = await create_pool()
    app.state.http = httpx.AsyncClient()
    cfg = get_settings()
    etl = None
    if cfg.etl_web_activo:
        etl = EjecutorWeb(cfg.database_url, cfg.etl_web_mem_mb, cfg.etl_web_max_s)
        etl.iniciar()
    log.info("backend iniciado")
    try:
        yield
    finally:
        if etl:
            await etl.detener()
        await app.state.http.aclose()
        await app.state.pool.close()


app = FastAPI(title="Almacenero API", version="0.0.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(v1_router)
errores.registrar(app)
