-- Calidad del catálogo (v0.0.2, corte 14; Doc 7). SQL plano, portable a cualquier Postgres.
-- El normalizador (etl/comun/normalizar.py) calcula estas columnas; acá solo la integridad.
-- Un producto `descartado` se conserva pero no se muestra: la app contesta «no encontrado»
-- hasta que alguien lo complete (admin o moderador) o una fuente lo mejore.

alter table productos_canonicos
    add column pack_cantidad       integer check (pack_cantidad > 1),
    add column presentacion        text,
    add column calidad             smallint check (calidad between 0 and 100),
    add column estado_calidad      text
        check (estado_calidad in ('completo', 'parcial', 'dudoso', 'descartado')),
    add column calidad_motivos     text[] not null default '{}',
    add column normalizador_version integer,
    -- puntaje y estado van juntos o ninguno (null = todavía sin evaluar)
    add constraint productos_canonicos_calidad_completa
        check ((calidad is null) = (estado_calidad is null));

-- «Dudosos primero» y los conteos del tablero.
create index productos_canonicos_estado_calidad_idx
    on productos_canonicos (estado_calidad, calidad);
