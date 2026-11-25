"""Consultas del dashboard de admin (docs/04 §11): tarjetas, series, rankings y productos estrella.

Sin tablas precalculadas: con el volumen actual alcanzan consultas directas con los índices que
hay. Toda la lógica de **zona horaria** está acá (docs/04 §11.3, regla 3): los instantes se
guardan y se devuelven en UTC; la zona (`config.panel_zona_horaria`) solo decide dónde empieza
cada hora/día/semana/mes. Los buckets vuelven como el instante UTC en que empiezan.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import asyncpg

from app.services import config as cfg

MAX_BARRAS = 1000

# granularidad -> (unidad de date_trunc, intervalo). Valores fijos: nunca se arma SQL con lo que
# manda el cliente.
GRANULARIDADES: dict[str, tuple[str, str]] = {
    "hora": ("hour", "1 hour"),
    "dia": ("day", "1 day"),
    "semana": ("week", "1 week"),  # date_trunc('week') arranca el lunes (ISO)
    "mes": ("month", "1 month"),
}

METRICAS = ("precios", "validaciones", "activos", "invitaciones")


class ZonaInvalida(ValueError):
    pass


class PeriodoInvalido(ValueError):
    pass


async def zona_valida(conn: asyncpg.Pool | asyncpg.Connection, zona: str) -> str:
    """Devuelve la zona si existe en la base de zonas (nombre exacto); si no, `ZonaInvalida`.
    Se compara contra `pg_timezone_names` para no aceptar siglas ambiguas (EST, ART)."""
    if not await conn.fetchval(
        "select exists (select 1 from pg_timezone_names where name = $1)", zona
    ):
        raise ZonaInvalida(zona)
    return zona


async def zona_del_panel(conn: asyncpg.Pool | asyncpg.Connection, pedida: str | None) -> str:
    return await zona_valida(conn, pedida or str(await cfg.leer(conn, "panel_zona_horaria")))


def _utc(t: datetime) -> datetime:
    """Un instante sin zona se toma como UTC (la API pide ISO-8601 con Z)."""
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


@dataclass(frozen=True)
class Periodo:
    desde: datetime
    hasta: datetime  # exclusivo


def periodo(desde: datetime | None, hasta: datetime | None, dias_por_defecto: int = 7) -> Periodo:
    h = _utc(hasta) if hasta else datetime.now(timezone.utc)
    d = _utc(desde) if desde else h - timedelta(days=dias_por_defecto)
    if d >= h:
        raise PeriodoInvalido("desde tiene que ser anterior a hasta")
    return Periodo(d, h)


# Cada fuente de la serie: (instante, usuario o null). `activos` mezcla tres fuentes.
_FUENTES = {
    "precios": "select created_at as ts, user_id as uid from precios",
    "validaciones": "select created_at as ts, user_id as uid from validaciones",
    "invitaciones": "select usada_en as ts, null::uuid as uid from invitaciones_usos",
    # Actividad = cargó un precio, un producto nuevo o una sugerencia (docs/04 §11.1).
    "activos": """
        select created_at as ts, user_id as uid from precios
        union all
        select created_at, usuario_id from auditoria_admin where accion = 'producto.crear'
        union all
        select created_at, usuario_id from sugerencias_catalogo
    """,
}


async def serie(
    conn: asyncpg.Pool | asyncpg.Connection,
    metrica: str,
    granularidad: str,
    p: Periodo,
    zona: str,
) -> list[dict]:
    """Un punto por bucket (incluidos los vacíos, en 0). `inicio_utc` es el instante UTC en que
    empieza el bucket local. Para `activos` cuenta usuarios distintos por bucket, separados en
    anónimos y registrados."""
    unidad, paso = GRANULARIDADES[granularidad]
    barras = (p.hasta - p.desde) / _duracion_aprox(granularidad)
    if barras > MAX_BARRAS:
        raise PeriodoInvalido(f"daría {int(barras)} barras (máximo {MAX_BARRAS})")
    if metrica == "activos":
        conteo = (
            "count(distinct x.uid), "
            "count(distinct x.uid) filter (where u.es_anonimo), "
            "count(distinct x.uid) filter (where not u.es_anonimo)"
        )
        union = "left join usuarios u on u.id = x.uid"
    else:
        conteo = "count(x.ts), null::bigint, null::bigint"
        union = ""
    rows = await conn.fetch(
        f"""
        with buckets as (
            select generate_series(
                       date_trunc('{unidad}', $1::timestamptz at time zone $3),
                       $2::timestamptz at time zone $3,
                       interval '{paso}') as local_ts
        ),
        fuente as (select ts, uid from ({_FUENTES[metrica]}) f where ts >= $1 and ts < $2)
        select b.local_ts at time zone $3 as inicio_utc, {conteo}
        from buckets b
        left join (
            select date_trunc('{unidad}', ts at time zone $3) as local_ts, ts, uid from fuente
        ) x
               on x.local_ts = b.local_ts
        {union}
        where b.local_ts < $2::timestamptz at time zone $3
        group by b.local_ts
        order by b.local_ts
        """,
        p.desde,
        p.hasta,
        zona,
    )
    return [
        {
            "inicio_utc": r[0],
            "valor": r[1],
            "anonimos": r[2],
            "registrados": r[3],
        }
        for r in rows
    ]


def _duracion_aprox(granularidad: str) -> timedelta:
    return {
        "hora": timedelta(hours=1),
        "dia": timedelta(days=1),
        "semana": timedelta(weeks=1),
        "mes": timedelta(days=28),  # el más corto: no subestima la cantidad de barras
    }[granularidad]


async def resumen(conn: asyncpg.Pool | asyncpg.Connection, p: Periodo) -> dict:
    """Las tarjetas. `activos` mira siempre los últimos N días (`dashboard_activo_dias`) hasta
    ahora, no el período elegido: «activo» es una definición, no un filtro."""
    dias = int(await cfg.leer(conn, "dashboard_activo_dias"))
    precios = await conn.fetchrow(
        "select count(*) filter (where created_at >= $1 and created_at < $2) as periodo, "
        "count(*) as total from precios",
        p.desde,
        p.hasta,
    )
    validaciones = await conn.fetchrow(
        "select count(*) filter (where created_at >= $1 and created_at < $2) as periodo, "
        "count(*) as total from validaciones",
        p.desde,
        p.hasta,
    )
    activos = await conn.fetchrow(
        f"""
        select count(distinct a.uid) filter (where u.es_anonimo) as anonimos,
               count(distinct a.uid) filter (where not u.es_anonimo) as registrados
        from ({_FUENTES["activos"]}) a(ts, uid)
        join usuarios u on u.id = a.uid
        where a.ts >= now() - make_interval(days => $1)
        """,
        dias,
    )
    invitaciones = await conn.fetchrow(
        """
        select count(*) as emitidas,
               count(*) filter (where usos_max is not null and usos >= usos_max) as usadas,
               count(*) filter (where not (usos_max is not null and usos >= usos_max)
                                  and vence is not null and vence <= now()) as vencidas,
               count(*) filter (where not (usos_max is not null and usos >= usos_max)
                                  and (vence is null or vence > now())) as disponibles
        from invitaciones
        """
    )
    usos = await conn.fetchrow(
        "select count(*) filter (where usada_en >= $1 and usada_en < $2) as periodo, "
        "count(*) as total from invitaciones_usos",
        p.desde,
        p.hasta,
    )
    return {
        "precios": dict(precios),
        "validaciones": dict(validaciones),
        "usuarios_activos": {"dias": dias, **dict(activos)},
        "invitaciones": {
            **dict(invitaciones),
            "aceptadas_periodo": usos["periodo"],
            "aceptadas_total": usos["total"],
        },
    }


_RANKINGS = {
    "productos": ("auditoria_admin", "usuario_id", "created_at", "accion = 'producto.crear'"),
    "precios": ("precios", "user_id", "created_at", "true"),
    "sugerencias": ("sugerencias_catalogo", "usuario_id", "created_at", "true"),
}


async def ranking(
    conn: asyncpg.Pool | asyncpg.Connection, tipo: str, p: Periodo, limite: int
) -> list[dict]:
    """Quién más carga (alias, nunca email) en el período."""
    tabla, col_usuario, col_fecha, filtro = _RANKINGS[tipo]
    rows = await conn.fetch(
        f"""
        select u.id, u.alias, u.rol, u.es_anonimo, count(*) as cantidad
        from {tabla} t join usuarios u on u.id = t.{col_usuario}
        where {filtro} and t.{col_fecha} >= $1 and t.{col_fecha} < $2
        group by u.id, u.alias, u.rol, u.es_anonimo
        order by cantidad desc, u.alias
        limit $3
        """,
        p.desde,
        p.hasta,
        limite,
    )
    return [dict(r) for r in rows]


async def estrellas(
    conn: asyncpg.Pool | asyncpg.Connection, p: Periodo, limite: int, via: str | None
) -> list[dict]:
    """Los EAN más escaneados por **usuarios distintos** (un solo usuario escaneando muchas
    veces no hace estrella a un producto). `via` filtra cámara o tipeado; sin `via` cuentan ambos
    (y también los eventos de apps viejas, que no traían `via`)."""
    rows = await conn.fetch(
        """
        select e.entidad_ref as ean,
               count(distinct e.usuario_id) as usuarios,
               count(*) as escaneos,
               bool_or((e.datos->>'encontrado')::boolean) as encontrado,
               p.nombre, p.marca
        from eventos e
        left join productos_canonicos p on p.ean = e.entidad_ref
        where e.tipo = 'producto.escaneado' and e.ocurrio_en >= $1 and e.ocurrio_en < $2
          and ($3::text is null or e.datos->>'via' = $3)
        group by e.entidad_ref, p.nombre, p.marca
        order by usuarios desc, escaneos desc, e.entidad_ref
        limit $4
        """,
        p.desde,
        p.hasta,
        via,
        limite,
    )
    return [dict(r) for r in rows]
