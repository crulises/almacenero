-- Corte 17: CSV curado (docs/04 §10-B). SQL plano, portable a cualquier Postgres.
-- `curado` es una fuente más del catálogo: lo que el dueño extrajo de las fuentes crudas,
-- ya normalizado, y revisó. Va entre lo manual y SEPA: manual > curado > sepa > off.

alter table productos_canonicos drop constraint productos_canonicos_origen_check;
alter table productos_canonicos
    add constraint productos_canonicos_origen_check
    check (origen in ('off', 'manual', 'sepa', 'curado'));

alter table producto_fuentes drop constraint producto_fuentes_fuente_check;
alter table producto_fuentes
    add constraint producto_fuentes_fuente_check check (fuente in ('off', 'sepa', 'curado'));

alter table conflictos_catalogo drop constraint conflictos_catalogo_fuente_a_check;
alter table conflictos_catalogo
    add constraint conflictos_catalogo_fuente_a_check
    check (fuente_a in ('off', 'manual', 'sepa', 'curado'));
alter table conflictos_catalogo drop constraint conflictos_catalogo_fuente_b_check;
alter table conflictos_catalogo
    add constraint conflictos_catalogo_fuente_b_check check (fuente_b in ('off', 'sepa', 'curado'));

-- Prioridad: config `catalogo_prioridad_fuentes` (de mayor a menor). Sin config:
-- manual > curado > sepa > off. Si la config guardada es anterior al corte 17 y no nombra
-- `curado`, queda justo después de `manual` (no al final, que lo dejaría debajo de OFF).
create or replace function prioridad_fuente(p_fuente text) returns integer
language sql stable as $$
    with lista as (
        select f, ord::int * 2 as pos
          from jsonb_array_elements_text(
                   coalesce((select valor from config
                              where clave = 'catalogo_prioridad_fuentes' and rubro is null),
                            '["manual", "curado", "sepa", "off"]'::jsonb)
               ) with ordinality as t(f, ord)
    )
    select coalesce(
        (select pos from lista where f = p_fuente),
        case when p_fuente = 'curado'
             then coalesce((select pos + 1 from lista where f = 'manual'), 1)
        end,
        1000
    );
$$;

-- Una fila por importación aplicada. El CSV NO se guarda: queda el dato (ya está en
-- productos_canonicos / producto_fuentes) y la receta para reconstruirlo (hash + versión +
-- hash de las fuentes de entrada).
create table catalogo_lotes (
    id                    uuid primary key default gen_random_uuid(),
    formato               text not null,
    version_normalizador  integer not null,
    nombre_archivo        text not null,
    -- sha256 del CONTENIDO (sin las líneas de comentario `#`): es lo que reproduce el exportador
    sha256                text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    sha256_declarado      text check (sha256_declarado ~ '^[0-9a-f]{64}$'),
    filas                 integer not null check (filas >= 0),
    nuevos                integer not null check (nuevos >= 0),
    cambiados             integer not null check (cambiados >= 0),
    iguales               integer not null check (iguales >= 0),
    invalidos             integer not null check (invalidos >= 0),
    -- [{nombre, sha256, bytes}] de los archivos crudos con que se armó el CSV
    fuentes_entrada       jsonb not null default '[]',
    subido_por            uuid references usuarios (id),
    etl_ejecucion_id      uuid,
    creado_en             timestamptz not null default now()
);

create index catalogo_lotes_sha256_idx on catalogo_lotes (sha256, version_normalizador);
