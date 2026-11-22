-- Corte 15: rol moderador y cola de sugerencias del catálogo (docs/04 §10-D, Doc 7 §5.1).
-- SQL plano, portable a cualquier Postgres.

-- ------------------------------------------------------------------ rol
-- Tercer rol. El trigger `proteger_rol` queda igual: el rol solo se cambia dentro de la
-- transacción del endpoint de admin.
alter table usuarios drop constraint usuarios_rol_check;
alter table usuarios
    add constraint usuarios_rol_check check (rol in ('usuario', 'moderador', 'admin'));

-- ------------------------------------------- «presentacion» también se puede bloquear
-- Quien completa un producto a mano fija también su presentación (botella, lata…); el ETL no
-- la pisa. El pack va junto con el tamaño (bloqueo `tamano`).
alter table productos_canonicos drop constraint productos_canonicos_campos_bloqueados_check;
alter table productos_canonicos
    add constraint productos_canonicos_campos_bloqueados_check
    check (campos_bloqueados <@ array['nombre', 'marca', 'tamano', 'presentacion']);

create or replace function proteger_campos_bloqueados() returns trigger
language plpgsql as $$
begin
    if coalesce(current_setting('app.catalogo_write', true), '') = 'on' then
        return new;
    end if;
    if 'nombre' = any (old.campos_bloqueados) and new.nombre is distinct from old.nombre then
        raise exception 'nombre bloqueado por resolución manual';
    end if;
    if 'marca' = any (old.campos_bloqueados) and new.marca is distinct from old.marca then
        raise exception 'marca bloqueada por resolución manual';
    end if;
    if 'tamano' = any (old.campos_bloqueados)
       and (new.tamano_valor is distinct from old.tamano_valor
            or new.tamano_unidad is distinct from old.tamano_unidad
            or new.pack_cantidad is distinct from old.pack_cantidad) then
        raise exception 'tamaño bloqueado por resolución manual';
    end if;
    if 'presentacion' = any (old.campos_bloqueados)
       and new.presentacion is distinct from old.presentacion then
        raise exception 'presentación bloqueada por resolución manual';
    end if;
    if new.campos_bloqueados is distinct from old.campos_bloqueados then
        raise exception 'campos_bloqueados solo se modifica al resolver un conflicto';
    end if;
    return new;
end;
$$;

-- ------------------------------------------------------- sugerencias_catalogo
-- Un moderador propone una corrección (producto existente) o un alta (producto nuevo, sin
-- `producto_id`). Un admin la aprueba —se aplica por el mismo camino que su corrección
-- directa— o la rechaza con una nota.
create table sugerencias_catalogo (
    id              uuid primary key default gen_random_uuid(),
    producto_id     uuid references productos_canonicos (id) on delete cascade,
    ean             text not null check (ean ~ '^[0-9]{8,14}$'),
    usuario_id      uuid not null references usuarios (id),
    cambios         jsonb not null check (
                        jsonb_typeof(cambios) = 'object' and cambios <> '{}'::jsonb
                        and (cambios - array['nombre', 'marca', 'tamano_valor', 'tamano_unidad',
                                             'pack_cantidad', 'presentacion']) = '{}'::jsonb),
    motivo          text check (char_length(motivo) <= 300),
    estado          text not null default 'pendiente'
                        check (estado in ('pendiente', 'aprobada', 'rechazada', 'reemplazada')),
    resuelto_por    uuid references usuarios (id),
    resuelto_en     timestamptz,
    nota_resolucion text check (char_length(nota_resolucion) <= 300),
    created_at      timestamptz not null default now(),
    -- pendiente <=> sin resolver; quien resuelve queda anotado salvo al reemplazarse sola
    check ((estado = 'pendiente') = (resuelto_en is null)),
    check (estado in ('pendiente', 'reemplazada') or resuelto_por is not null),
    check (estado <> 'rechazada' or nota_resolucion is not null)
);

-- Una sola sugerencia pendiente por producto (o por EAN, si es un alta) y usuario.
create unique index sugerencias_pendiente_uidx
    on sugerencias_catalogo (ean, usuario_id) where estado = 'pendiente';
create index sugerencias_estado_idx on sugerencias_catalogo (estado, created_at);
create index sugerencias_producto_idx on sugerencias_catalogo (producto_id);

-- El rastro de auditoría del panel acepta la entidad nueva.
alter table auditoria_admin drop constraint auditoria_admin_entidad_check;
alter table auditoria_admin add constraint auditoria_admin_entidad_check
    check (entidad in ('local', 'precio', 'config', 'producto', 'conflicto', 'usuario',
                       'invitacion', 'sugerencia'));
