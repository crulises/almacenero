"""Mensajes de error de las reglas de negocio, editables desde el panel (docs/04 §10-E).

El código y la regla no se tocan: solo el texto que ve quien recibe el error. Un texto vacío
vuelve al por defecto. Se guarda en `config.mensajes_reglas` y queda en la auditoría.
"""

import json

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import Usuario
from app.db import get_pool
from app.services import auditoria, reglas
from app.services.permisos import exigir

router = APIRouter(tags=["admin"])


class ReglaOut(BaseModel):
    codigo: str
    titulo: str
    mensaje_default: str
    mensaje: str  # el que rige hoy (el editado, si lo hay)
    editado: bool
    como_resolver: str
    status: int


class MensajeIn(BaseModel):
    mensaje: str  # vacío = volver al por defecto


def _salida(editados: dict[str, str]) -> list[ReglaOut]:
    out = []
    for r in reglas.REGLAS.values():
        propio = (editados.get(r.codigo) or "").strip()
        out.append(
            ReglaOut(
                codigo=r.codigo,
                titulo=r.titulo,
                mensaje_default=r.mensaje,
                mensaje=propio or r.mensaje,
                editado=bool(propio),
                como_resolver=r.como_resolver,
                status=r.status,
            )
        )
    return out


@router.get("/reglas", response_model=list[ReglaOut])
async def ver_reglas(
    _: Usuario = Depends(exigir("config.editar")), pool: asyncpg.Pool = Depends(get_pool)
) -> list[ReglaOut]:
    return _salida(await reglas.mensajes(pool))


@router.put("/reglas/{codigo}", response_model=ReglaOut)
async def cambiar_mensaje(
    codigo: str,
    body: MensajeIn,
    admin: Usuario = Depends(exigir("config.editar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ReglaOut:
    if codigo not in reglas.REGLAS:
        raise HTTPException(404, "regla desconocida")
    texto = body.mensaje.strip()
    if len(texto) > 400:
        raise HTTPException(422, "el mensaje puede tener hasta 400 caracteres")
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("select pg_advisory_xact_lock(hashtext($1))", reglas.CLAVE_CONFIG)
        editados = await reglas.mensajes(conn)
        antes = editados.get(codigo)
        if texto:
            editados[codigo] = texto
        else:
            editados.pop(codigo, None)
        await conn.execute(
            """
            insert into config (clave, valor, rubro) values ($1, $2::jsonb, null)
            on conflict (clave, coalesce(rubro, '')) do update set valor = excluded.valor
            """,
            reglas.CLAVE_CONFIG,
            json.dumps(editados),
        )
        await auditoria.registrar(
            conn,
            admin.id,
            "reglas.mensaje",
            "config",
            reglas.CLAVE_CONFIG,
            {codigo: antes},
            {codigo: texto or None},
        )
    return next(r for r in _salida(editados) if r.codigo == codigo)
