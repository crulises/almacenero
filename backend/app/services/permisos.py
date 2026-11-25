"""Quién puede hacer qué.

Los endpoints no preguntan «¿es admin?»: preguntan por una **capacidad con nombre**
(`puede(usuario, "local.verificar")`). Hoy el rol sale de una columna y el mapa
rol → capacidades es un diccionario. Si el modelo crece (moderadores, permisos por
local, permisos editables), se cambia ESTE módulo y una migración; los endpoints
no se tocan. Ver docs/04-plan-v0.1.md, §1.
"""

from typing import Protocol

from fastapi import Depends, HTTPException

from app.auth import Usuario, current_user


class _ConRol(Protocol):
    rol: str


CAPACIDADES: dict[str, frozenset[str]] = {
    "usuario": frozenset({"precio.cargar", "local.proponer"}),
    # Moderador (docs/04 §10-D): como un usuario, y además propone cambios al catálogo.
    "moderador": frozenset({"precio.cargar", "local.proponer", "catalogo.sugerir"}),
    "admin": frozenset(
        {
            "precio.cargar",
            "local.proponer",
            "local.crear",
            "local.verificar",
            # Panel web de admin (/v1/admin, corte 11)
            "admin.acceder",
            "usuario.ver",
            "usuario.editar",
            "usuario.cambiar_rol",
            "usuario.ajustar_karma",
            "usuario.dar_baja",
            "local.editar",
            "local.fusionar",
            "local.borrar",
            "precio.corregir",
            "precio.borrar",
            "config.editar",
            "catalogo.editar",
            "catalogo.resolver",
            "catalogo.crear",
            "catalogo.sugerir",
            "catalogo.sugerencias.resolver",
            "auditoria.ver",
            # Invitaciones / PINs (corte 9)
            "invitacion.ver",
            "invitacion.emitir",
            # ETL desde el panel (corte 18): solo admin
            "etl.ver",
            "etl.ejecutar",
            "etl.cancelar",
            "etl.programar",  # programaciones (cron) y prueba del almacén, corte 19c
            # Dashboard de admin (corte 19): solo admin
            "dashboard.ver",
        }
    ),
}


# Lo que ESCRIBE información (docs/04 §9): un usuario restringido por karma no puede.
# Leer / consultar no está acá: sigue andando.
CAPACIDADES_DE_CARGA = frozenset(
    {"precio.cargar", "local.proponer", "local.crear", "catalogo.sugerir"}
)

CUENTA_RESTRINGIDA = {
    "codigo": "cuenta_restringida",
    "mensaje": "tu karma está muy bajo: por ahora solo podés consultar, no cargar",
}


def puede(usuario: _ConRol, capacidad: str) -> bool:
    if capacidad in CAPACIDADES_DE_CARGA and getattr(usuario, "escalon", "normal") == "restringido":
        return False
    return capacidad in CAPACIDADES.get(usuario.rol, frozenset())


def exigir_carga(usuario: Usuario) -> None:
    """403 `cuenta_restringida` si el usuario está en el escalón de restricción. Único
    punto que decide «no podés cargar»: lo usan los endpoints que escriben."""
    if getattr(usuario, "escalon", "normal") == "restringido":
        raise HTTPException(403, detail=CUENTA_RESTRINGIDA)


def exigir(capacidad: str):
    """Dependencia de FastAPI: 403 si el usuario no tiene la capacidad."""

    async def dependencia(user: Usuario = Depends(current_user)) -> Usuario:
        if capacidad in CAPACIDADES_DE_CARGA:
            exigir_carga(user)
        if not puede(user, capacidad):
            raise HTTPException(403, "no tenés permiso para esto")
        return user

    return dependencia
