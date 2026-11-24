from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    avisos,
    config,
    eventos,
    health,
    locales,
    me,
    precios,
    productos,
    sugerencias,
)

router = APIRouter(prefix="/v1")
router.include_router(health.router)
router.include_router(admin.router)
router.include_router(auth.router)
router.include_router(me.router)
router.include_router(avisos.router)
router.include_router(config.router)
router.include_router(eventos.router)
router.include_router(locales.router)
router.include_router(productos.router)
router.include_router(precios.router)
router.include_router(sugerencias.router)
