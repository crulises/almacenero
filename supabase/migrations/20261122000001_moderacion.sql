-- Corte 12: moderación (docs/04 §9). Estado de la cuenta: activo | baja.
-- El escalón por karma (aviso / restringido) NO se guarda: se deduce del karma y de los
-- umbrales de `config`, para que nunca se contradigan.

alter table usuarios
    add column estado  text not null default 'activo' check (estado in ('activo', 'baja')),
    add column baja_at timestamptz;

-- Baja con fecha, activo sin fecha.
alter table usuarios
    add constraint usuarios_baja_coherente
    check ((estado = 'baja') = (baja_at is not null));

-- Igual que el rol y el karma: el estado no se cambia por la API de un usuario común.
-- Solo dentro de una transacción que lo habilite (el endpoint de admin).
create function proteger_estado() returns trigger
language plpgsql as $$
begin
    if tg_op = 'INSERT' then
        if new.estado <> 'activo'
           and coalesce(current_setting('app.estado_write', true), '') <> 'on' then
            raise exception 'estado no se puede setear directamente';
        end if;
    elsif (new.estado is distinct from old.estado or new.baja_at is distinct from old.baja_at)
          and coalesce(current_setting('app.estado_write', true), '') <> 'on' then
        raise exception 'estado no se puede modificar directamente';
    end if;
    return new;
end;
$$;

create trigger usuarios_proteger_estado
    before insert or update on usuarios
    for each row execute function proteger_estado();

-- Para filtrar el listado del panel por estado.
create index usuarios_estado_idx on usuarios (estado) where estado <> 'activo';
