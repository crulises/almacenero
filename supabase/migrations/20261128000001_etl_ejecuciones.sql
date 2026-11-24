-- Corte 18: ETL desde el panel (docs/04 §10-A). SQL plano, portable a cualquier Postgres.
-- Una cola de ejecuciones en Postgres: el panel encola, y un ejecutor `web` (subproceso del
-- backend, para lo liviano) o `local` (worker en la máquina del dueño, para lo pesado) la toma.

create table etl_ejecuciones (
    id            uuid primary key default gen_random_uuid(),
    etl           text not null,            -- clave de la definición (etl/registro.py)
    parametros    jsonb not null default '{}',
    estado        text not null default 'en_cola'
                  check (estado in ('en_cola', 'corriendo', 'cancelando', 'ok', 'fallo', 'cancelada')),
    ejecutor      text not null check (ejecutor in ('web', 'local')),
    creado_por    uuid references usuarios (id),
    creado_en     timestamptz not null default now(),
    iniciado_en   timestamptz,
    terminado_en  timestamptz,
    -- el ejecutor lo renueva cada pocos segundos; sin latido por 2 minutos = se murió
    latido_en     timestamptz,
    reporte       jsonb,                     -- lo que informa el ETL (filas, nuevos, ...)
    filas         integer,                   -- filas leídas, para el listado
    log           text not null default '',  -- últimas ~64 KB
    cancelar      boolean not null default false,
    check ((estado in ('ok', 'fallo', 'cancelada')) = (terminado_en is not null)),
    check (estado in ('en_cola') or iniciado_en is not null or estado = 'cancelada')
);

-- Una sola ejecución a la vez por ejecutor.
create unique index etl_ejecuciones_una_corriendo_idx
    on etl_ejecuciones (ejecutor) where estado in ('corriendo', 'cancelando');
create index etl_ejecuciones_cola_idx on etl_ejecuciones (creado_en) where estado = 'en_cola';
create index etl_ejecuciones_recientes_idx on etl_ejecuciones (creado_en desc);

-- Archivos que entran por el panel (el CSV curado). Viven acá, temporalmente, y no en disco:
-- el disco de Fly es efímero y así los ve igual el ejecutor `web` y el `local`. Se borran al
-- importar de verdad (o a las 24 h); queda solo el metadato en `etl_ejecuciones.parametros`.
create table etl_archivos (
    id          uuid primary key default gen_random_uuid(),
    nombre      text not null,
    sha256      text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    tamano      integer not null check (tamano > 0 and tamano <= 26214400),  -- 25 MiB
    contenido   bytea not null,
    subido_por  uuid references usuarios (id),
    creado_en   timestamptz not null default now()
);

alter table catalogo_lotes
    add constraint catalogo_lotes_etl_ejecucion_fk
    foreign key (etl_ejecucion_id) references etl_ejecuciones (id) on delete set null;
