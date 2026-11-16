-- Roles de usuario y alta de locales por usuarios (v0.0.2, corte 5).
-- SQL plano, portable a cualquier Postgres con PostGIS.

create extension if not exists pg_trgm;

-- ------------------------------------------------------------------- roles
-- Hoy dos roles. Si aparece un tercero (moderador) se amplía este check.
alter table usuarios
    add column rol text not null default 'usuario'
    check (rol in ('usuario', 'admin'));

-- El rol no se cambia por la API: solo con SQL, y dentro de una transacción que
-- lo habilite (igual que el karma). `make admin ALIAS=...` lo hace por vos.
create function proteger_rol() returns trigger
language plpgsql as $$
begin
    if tg_op = 'INSERT' then
        if new.rol <> 'usuario'
           and coalesce(current_setting('app.rol_write', true), '') <> 'on' then
            raise exception 'rol no se puede setear directamente';
        end if;
    elsif new.rol is distinct from old.rol
          and coalesce(current_setting('app.rol_write', true), '') <> 'on' then
        raise exception 'rol no se puede modificar directamente';
    end if;
    return new;
end;
$$;

create trigger usuarios_proteger_rol
    before insert or update on usuarios
    for each row execute function proteger_rol();

-- ----------------------------------------------------------------- locales
-- Un local creado por un usuario nace sin verificar (pero usable); el admin lo
-- verifica, corrige o fusiona. Los locales que ya existían los cargó el admin.
alter table locales add column verificado boolean not null default false;
update locales set verificado = true;

-- Para comparar nombres por similitud (anti-duplicados).
create index locales_nombre_trgm_idx on locales using gin (lower(nombre) gin_trgm_ops);

-- Los que crea cada usuario, para el límite diario.
create index locales_creado_por_idx on locales (creado_por, created_at);
