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
    # Anti-spam (docs/04 §6). Seguro por defecto: sin la fila, se exige invitación.
    "modo_acceso": "solo_invitacion",  # abierto | solo_invitacion | alta_manual
    "auth_altas_por_hora_ip": 10,  # /auth/anonymous, cuenta todos los intentos
    "auth_refresh_por_hora_ip": 120,
    "max_precios_por_hora": 60,
    "max_precios_por_dia": 300,
    # Moderación (docs/04 §9): el karma se compara con `<=`. Son negativos a propósito.
    "karma_umbral_aviso": -5,  # desde acá la app avisa; sigue usando todo
    "karma_umbral_restriccion": -15,  # desde acá no puede cargar; sí consultar
    # Mensajes de error editados desde el panel: {codigo_de_regla: texto} (services/reglas.py).
    "mensajes_reglas": {},
    # Moderador (docs/04 §10-D): karma que gana al aprobarse una sugerencia suya.
    "karma_sugerencia_aprobada": 3,
    # Eventos de producto (docs/04 §11.2): tope de filas antes de avisar/exportar (corte 19c) y
    # de lotes por usuario por hora (la app junta los eventos y los manda de a tandas).
    "eventos_max_filas": 100000,
    "max_lotes_eventos_por_hora": 120,
    # Dashboard de admin (docs/04 §11): zona en que se muestran y agrupan las fechas (los instantes
    # siguen en UTC) y ventana de «usuario activo» (hizo una carga en los últimos N días).
    "panel_zona_horaria": "America/Buenos_Aires",
    "dashboard_activo_dias": 7,
    # Mapa de zonas (docs/04 §11.5): lado de la celda en metros y mínimo de precios para dibujarla
    # (una celda con 1-2 precios señalaría a un comercio suelto).
    "dashboard_celda_m": 1000,
    "dashboard_celda_min_precios": 5,
    # Exportar eventos (docs/04 §11.4): tope por archivo (el plan Free de Supabase admite 50 MB).
    "eventos_export_filas_por_archivo": 500000,
}


async def leer(conn: asyncpg.Pool | asyncpg.Connection, clave: str) -> Any:
    valor = await conn.fetchval(
        "select valor::text from config where clave = $1 and rubro is null", clave
    )
    return DEFAULTS.get(clave) if valor is None else json.loads(valor)
