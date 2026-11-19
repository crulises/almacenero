"""Capa común de los ETL de LOCALES (OpenStreetMap, sucursales de SEPA).

Cada ETL transforma su formato a `Local` y acá se fusionan con `locales`:

1. Si el registro de la fuente ya está vinculado (`local_fuentes`: fuente + ref),
   solo se refresca el dato crudo; el local no se toca (puede haberlo corregido
   el admin).
2. Si no, se busca un duplicado con la misma lógica del alta de locales del
   backend (corte 5): nombre parecido (pg_trgm) a pocos metros, con los umbrales
   de config `local_duplicado_similitud` y `local_duplicado_metros`. Si existe, no
   se crea nada: se le agrega el vínculo a esta fuente.
3. Si no, se crea el local con `verificado = false`, `creado_por = null` y
   `fuente` = la que lo trajo, más el vínculo.

Idempotente: correrlo de nuevo no crea ni vincula nada. Se procesa local por local
(miles por provincia); para volúmenes de país o mundo, pasar a staging + SQL por
conjuntos como en `catalogo.py`.
"""

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

import asyncpg

METROS_DEFECTO = 50.0
SIMILITUD_DEFECTO = 0.8
MAX_NOMBRE = 200
MAX_DIRECCION = 300


@dataclass
class Local:
    fuente: str  # 'osm' | 'sepa'
    ref: str  # 'node/123' | 'id_comercio-id_bandera-id_sucursal'
    nombre: str
    direccion: str | None
    lat: float
    lng: float
    datos: dict = field(default_factory=dict)  # crudo de la fuente, para `local_fuentes`


@dataclass
class ReporteLocales:
    leidos: int = 0
    descartados: Counter = field(default_factory=Counter)
    nuevos: int = 0
    vinculados_a_existente: int = 0
    refrescados: int = 0

    @property
    def total_descartados(self) -> int:
        return sum(self.descartados.values())

    def texto(self) -> str:
        lineas = [
            f"Registros leídos:              {self.leidos}",
            f"Locales nuevos:                {self.nuevos}",
            f"Vinculados a un local que ya existía (duplicado): {self.vinculados_a_existente}",
            f"Ya cargados antes (refrescados): {self.refrescados}",
            f"Descartados:                   {self.total_descartados}",
        ]
        lineas += [f"    {motivo}: {n}" for motivo, n in self.descartados.most_common()]
        return "\n".join(lineas)


async def _umbral(conn: asyncpg.Connection, clave: str, defecto: float) -> float:
    valor = await conn.fetchval(
        "select valor #>> '{}' from config where clave = $1 and rubro is null", clave
    )
    return float(valor) if valor is not None else defecto


_SQL_DUPLICADO = """
select l.id
from locales l
where st_dwithin(l.ubicacion, st_setsrid(st_makepoint($2, $1), 4326)::geography, $3)
  and similarity(lower(unaccent(l.nombre)), lower(unaccent($4))) >= $5
order by similarity(lower(unaccent(l.nombre)), lower(unaccent($4))) desc
limit 1
"""

_SQL_NUEVO = """
insert into locales (nombre, direccion, ubicacion, fuente, verificado, creado_por)
values ($1, $2, st_setsrid(st_makepoint($4, $3), 4326)::geography, $5, false, null)
returning id
"""

_SQL_VINCULO = """
insert into local_fuentes (local_id, fuente, ref, datos) values ($1, $2, $3, $4::jsonb)
"""


async def fusionar_locales(
    conn: asyncpg.Connection, locales: Iterable[Local], reporte: ReporteLocales
) -> None:
    metros = await _umbral(conn, "local_duplicado_metros", METROS_DEFECTO)
    similitud = await _umbral(conn, "local_duplicado_similitud", SIMILITUD_DEFECTO)
    for loc in locales:
        datos = json.dumps(loc.datos, ensure_ascii=False)
        async with conn.transaction():
            ya = await conn.execute(
                "update local_fuentes set datos = $3::jsonb, cargado_en = now() "
                "where fuente = $1 and ref = $2",
                loc.fuente,
                loc.ref,
                datos,
            )
            if ya != "UPDATE 0":
                reporte.refrescados += 1
                continue
            existente = await conn.fetchval(
                _SQL_DUPLICADO, loc.lat, loc.lng, metros, loc.nombre, similitud
            )
            if existente is not None:
                reporte.vinculados_a_existente += 1
                local_id = existente
            else:
                local_id = await conn.fetchval(
                    _SQL_NUEVO,
                    loc.nombre[:MAX_NOMBRE],
                    loc.direccion[:MAX_DIRECCION] if loc.direccion else None,
                    loc.lat,
                    loc.lng,
                    loc.fuente,
                )
                reporte.nuevos += 1
            await conn.execute(_SQL_VINCULO, local_id, loc.fuente, loc.ref, datos)
