"""Quién puede hacer qué.

Los endpoints no preguntan «¿es admin?»: preguntan por una **capacidad con nombre**
(`puede(usuario, "local.verificar")`). Hoy el rol sale de una columna y el mapa
rol → capacidades es un diccionario. Si el modelo crece (moderadores, permisos por
local, permisos editables), se cambia ESTE módulo y una migración; los endpoints
no se tocan. Ver docs/04-plan-v0.0.2.md, §1.
"""

from typing import Protocol

from fastapi import Depends, HTTPException

from app.auth import Usuario, current_user


class _ConRol(Protocol):
    rol: str


CAPACIDADES: dict[str, frozenset[str]] = {
    "usuario": frozenset({"precio.cargar", "local.proponer"}),
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
            "local.editar",
            "local.fusionar",
            "local.borrar",
            "precio.corregir",
            "precio.borrar",
            "config.editar",
            "catalogo.editar",
            "catalogo.resolver",
            "auditoria.ver",
            # Invitaciones / PINs (corte 9)
            "invitacion.ver",
            "invitacion.emitir",
        }
    ),
}


def puede(usuario: _ConRol, capacidad: str) -> bool:
    return capacidad in CAPACIDADES.get(usuario.rol, frozenset())


def exigir(capacidad: str):
    """Dependencia de FastAPI: 403 si el usuario no tiene la capacidad."""

    async def dependencia(user: Usuario = Depends(current_user)) -> Usuario:
        if not puede(user, capacidad):
            raise HTTPException(403, "no tenés permiso para esto")
        return user

    return dependencia
