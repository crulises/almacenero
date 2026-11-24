-- Eventos de producto (docs/04 §11.2): una tabla genérica; el registro de tipos vive en el
-- backend (services/eventos.py), así un evento nuevo no necesita migración.
create table eventos (
    id          bigint generated always as identity primary key,
    tipo        text not null check (tipo ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$'),
    -- El instante (UTC) lo pone el servidor; el reloj del celular, si viene, va dentro de `datos`.
    ocurrio_en  timestamptz not null default now(),
    usuario_id  uuid references usuarios (id) on delete set null,
    entidad     text,
    entidad_ref text,
    datos       jsonb not null default '{}'
);

create index eventos_tipo_ocurrio_idx on eventos (tipo, ocurrio_en);
create index eventos_tipo_entidad_idx on eventos (tipo, entidad_ref);
create index eventos_usuario_ocurrio_idx on eventos (usuario_id, ocurrio_en);

-- Solo el backend escribe y lee eventos; PostgREST (anon/authenticated) no tiene que verlos.
alter table eventos enable row level security;
