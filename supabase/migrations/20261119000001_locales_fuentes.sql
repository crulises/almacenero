-- Locales cargados por ETL (v0.0.2, corte 7): OpenStreetMap y sucursales de SEPA.
-- Entran sin verificar y sin dueño (`creado_por` null). Cada local guarda de qué
-- fuente(s) salió, para no duplicarlo al recargar y para poder separar los datos
-- por licencia (OSM es ODbL). SQL plano, portable a cualquier Postgres.

-- Cómo nació el local: por un usuario/admin (manual) o por un ETL.
alter table locales
    add column fuente text not null default 'manual'
    check (fuente in ('manual', 'osm', 'sepa'));

-- Vínculo local <-> registro de la fuente. Un local puede tener varios (el mismo
-- comercio en OSM y en SEPA); un registro de la fuente apunta a un solo local.
--   osm  -> ref = 'node/123', 'way/456' (tipo y id de OSM)
--   sepa -> ref = 'id_comercio-id_bandera-id_sucursal'
create table local_fuentes (
    id          uuid primary key default gen_random_uuid(),
    local_id    uuid not null references locales (id) on delete cascade,
    fuente      text not null check (fuente in ('osm', 'sepa')),
    ref         text not null check (length(ref) between 1 and 100),
    datos       jsonb not null default '{}'::jsonb,
    cargado_en  timestamptz not null default now(),
    unique (fuente, ref)
);

create index local_fuentes_local_idx on local_fuentes (local_id);
