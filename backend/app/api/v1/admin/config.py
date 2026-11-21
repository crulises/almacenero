import json
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import Usuario
from app.db import get_pool
from app.services import auditoria
from app.services.config import DEFAULTS
from app.services.permisos import exigir

router = APIRouter(tags=["admin"])

# Umbrales de moderación (docs/04 §9) → el otro de la pareja.
UMBRALES_KARMA = {
    "karma_umbral_aviso": "karma_umbral_restriccion",
    "karma_umbral_restriccion": "karma_umbral_aviso",
}


class ConfigItem(BaseModel):
    clave: str
    valor: Any
    rubro: str | None
    default: Any = None
    en_base: bool  # false: la clave no está en la base y rige el default del código


class ConfigIn(BaseModel):
    valor: Any


def _tipo(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int | float):
        return "numero"
    if isinstance(v, str):
        return "texto"
    if isinstance(v, list):
        return "lista"
    return "otro"


@router.get("/config", response_model=list[ConfigItem])
async def ver_config(
    _: Usuario = Depends(exigir("config.editar")), pool: asyncpg.Pool = Depends(get_pool)
) -> list[ConfigItem]:
    rows = await pool.fetch("select clave, valor::text as valor, rubro from config order by clave")
    items = [
        ConfigItem(
            clave=r["clave"],
            valor=json.loads(r["valor"]),
            rubro=r["rubro"],
            default=DEFAULTS.get(r["clave"]),
            en_base=True,
        )
        for r in rows
    ]
    en_base = {i.clave for i in items if i.rubro is None}
    for clave, default in DEFAULTS.items():
        if clave not in en_base:
            items.append(
                ConfigItem(clave=clave, valor=default, rubro=None, default=default, en_base=False)
            )
    return sorted(items, key=lambda i: (i.clave, i.rubro or ""))


@router.put("/config/{clave}", response_model=ConfigItem)
async def cambiar_config(
    clave: str,
    body: ConfigIn,
    admin: Usuario = Depends(exigir("config.editar")),
    pool: asyncpg.Pool = Depends(get_pool),
) -> ConfigItem:
    """Cambia el valor global (`rubro` nulo) de una clave que ya existe en la base o tiene
    default en el código. Se valida que el tipo coincida con el actual."""
    async with pool.acquire() as conn, conn.transaction():
        previo = await conn.fetchval(
            "select valor::text from config where clave = $1 and rubro is null for update", clave
        )
        if previo is None and clave not in DEFAULTS:
            raise HTTPException(404, "clave de configuración desconocida")
        actual = json.loads(previo) if previo is not None else DEFAULTS[clave]
        if _tipo(body.valor) != _tipo(actual):
            raise HTTPException(
                422, f"el valor tiene que ser de tipo {_tipo(actual)} (como el actual)"
            )
        if clave in UMBRALES_KARMA:
            # Son negativos a propósito (karma <= umbral). La escalera tiene que bajar:
            # primero el aviso, después la restricción.
            if body.valor > 0:
                raise HTTPException(422, "el umbral de karma tiene que ser cero o negativo")
            otra = UMBRALES_KARMA[clave]
            valor_otra = await conn.fetchval(
                "select valor::text from config where clave = $1 and rubro is null", otra
            )
            valor_otra = json.loads(valor_otra) if valor_otra is not None else DEFAULTS[otra]
            aviso, restriccion = (
                (body.valor, valor_otra)
                if clave == "karma_umbral_aviso"
                else (valor_otra, body.valor)
            )
            if restriccion > aviso:
                raise HTTPException(
                    422, "el umbral de restricción no puede estar por encima del de aviso"
                )
        elif _tipo(actual) == "numero" and body.valor < 0:
            raise HTTPException(422, "el valor no puede ser negativo")
        await conn.execute(
            """
            insert into config (clave, valor, rubro) values ($1, $2::jsonb, null)
            on conflict (clave, coalesce(rubro, '')) do update set valor = excluded.valor
            """,
            clave,
            json.dumps(body.valor),
        )
        await auditoria.registrar(
            conn,
            admin.id,
            "config.cambiar",
            "config",
            clave,
            {"valor": actual},
            {"valor": body.valor},
            nota=None if previo is not None else "la clave no estaba en la base",
        )
    return ConfigItem(
        clave=clave, valor=body.valor, rubro=None, default=DEFAULTS.get(clave), en_base=True
    )
