-- Corte 19c (docs/04 §11.4): exportar y vaciar eventos, y programar ETL. SQL plano, portable.

-- Cada archivo que `eventos_exportar` dejó en el almacén. Se escribe en la MISMA transacción que
-- borra los eventos exportados: o quedan las dos cosas o ninguna.
create table eventos_exportaciones (
    id           uuid primary key default gen_random_uuid(),
    ejecucion_id uuid references etl_ejecuciones (id) on delete set null,
    tipo         text,                                   -- filtro usado (null = todos los tipos)
    id_desde     bigint not null,                        -- rango de ids de `eventos` de ESTE archivo
    id_hasta     bigint not null check (id_hasta >= id_desde),
    filas        integer not null check (filas > 0),
    sha256       text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    tamano       bigint not null check (tamano > 0),
    clave        text not null,                          -- nombre dentro del almacén
    almacen      text not null check (almacen in ('s3', 'disco')),
    borradas     integer not null default 0 check (borradas >= 0),  -- 0 = se exportó sin vaciar
    creado_en    timestamptz not null default now()
);
create index eventos_exportaciones_creado_idx on eventos_exportaciones (creado_en desc);

-- Programación de ETL (cron interpretado en UTC). No se usa pg_cron a propósito: ataría el
-- proyecto a una extensión del proveedor. Un ciclo del backend (con un lock de Postgres, para que
-- con varias réplicas corra una sola) encola en la misma cola `etl_ejecuciones`.
create table etl_programaciones (
    id                  uuid primary key default gen_random_uuid(),
    etl                 text not null,
    parametros          jsonb not null default '{}',
    cron                text not null check (length(cron) between 9 and 100),
    activa              boolean not null default false,
    -- solo para eventos_exportar: además del cron, encolar al pasar `config.eventos_max_filas`
    al_superar_umbral   boolean not null default false,
    ultima_corrida      timestamptz,
    proxima_corrida     timestamptz,
    ultima_ejecucion_id uuid references etl_ejecuciones (id) on delete set null,
    creado_por          uuid references usuarios (id) on delete set null,
    creado_en           timestamptz not null default now()
);
create index etl_programaciones_proxima_idx on etl_programaciones (proxima_corrida) where activa;

-- Solo el backend las toca; PostgREST (anon/authenticated) no tiene que verlas.
alter table eventos_exportaciones enable row level security;
alter table etl_programaciones enable row level security;
