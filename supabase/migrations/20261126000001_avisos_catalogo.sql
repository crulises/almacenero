-- Corte 15 (ajuste): avisos de catálogo. Cuando el normalizador ajusta lo que una persona
-- cargó a mano (nombre con marca/tamaño/envase adentro, abreviaturas, mayúsculas…), se le
-- deja un aviso con el porqué y los estándares de carga que no se cumplían. Es solo
-- información: no toca el karma. SQL plano, portable a cualquier Postgres.

create table avisos_catalogo (
    id          uuid primary key default gen_random_uuid(),
    usuario_id  uuid not null references usuarios (id),
    producto_id uuid references productos_canonicos (id) on delete cascade,
    ean         text not null check (ean ~ '^[0-9]{8,14}$'),
    tipo        text not null check (tipo in ('nombre_ajustado')),
    -- ids de backend/app/services/estandares.py
    estandares  text[] not null check (cardinality(estandares) > 0),
    antes       jsonb not null,
    despues     jsonb not null,
    created_at  timestamptz not null default now(),
    leido_en    timestamptz
);

create index avisos_usuario_idx on avisos_catalogo (usuario_id, created_at desc);
create index avisos_no_leidos_idx on avisos_catalogo (usuario_id) where leido_en is null;
