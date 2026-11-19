"""Lectura de tunables (`config`) con valor por defecto en código.

Si la clave falta en la base (p. ej. una base nueva sin seed), se usa el default:
el backend no depende de que el seed de desarrollo se haya corrido.
"""

import json
from typing import Any

import asyncpg

DEFAULTS: dict[str, Any] = {
    "geofence_metros": 150,
    "geofence_precision_max_m": 100,  # GPS peor que esto: se pide reintentar
    "radio_precios_m": 5000,  # precios vigentes: solo locales a esta distancia
    "ventana_frescura_dias": 30,
    "umbral_verde_dias": 7,
    "umbral_amarillo_dias": 21,
    "alta_locales_abierta": False,  # seguro por defecto: solo admin (Doc 1)
    "max_locales_por_dia": 50,
    "local_duplicado_metros": 50,
    "local_duplicado_similitud": 0.8,
}


async def leer(conn: asyncpg.Pool | asyncpg.Connection, clave: str) -> Any:
    valor = await conn.fetchval(
        "select valor::text from config where clave = $1 and rubro is null", clave
    )
    return DEFAULTS.get(clave) if valor is None else json.loads(valor)
