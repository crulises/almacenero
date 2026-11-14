-- Esquema inicial (v0.0.1). SQL plano, portable a cualquier Postgres con PostGIS.
-- La lógica de integridad vive acá; la de negocio vive en el backend.

create extension if not exists postgis;

-- ---------------------------------------------------------------- usuarios
-- auth_id referencia al usuario del proveedor de auth (Supabase/GoTrue), pero SIN
-- foreign key: así el esquema no depende del schema `auth` y es portable.
create table usuarios (
    id          uuid primary key default gen_random_uuid(),
    auth_id     uuid not null unique,
    alias       text not null check (length(alias) between 1 and 50),
    karma       integer not null default 0,
    created_at  timestamptz not null default now()
);

-- El karma no se escribe a mano: solo el backend, que habilita la escritura
-- dentro de su transacción con: select set_config('app.karma_write', 'on', true);
create function proteger_karma() returns trigger
language plpgsql as $$
begin
    if tg_op = 'INSERT' then
        if new.karma <> 0
           and coalesce(current_setting('app.karma_write', true), '') <> 'on' then
            raise exception 'karma no se puede setear directamente';
        end if;
    elsif new.karma is distinct from old.karma
          and coalesce(current_setting('app.karma_write', true), '') <> 'on' then
        raise exception 'karma no se puede modificar directamente';
    end if;
    return new;
end;
$$;

create trigger usuarios_proteger_karma
    before insert or update on usuarios
    for each row execute function proteger_karma();

-- ----------------------------------------------------------------- locales
create table locales (
    id              uuid primary key default gen_random_uuid(),
    nombre          text not null,
    direccion       text,
    ubicacion       geography(point, 4326) not null,
    medios_pago     jsonb not null default '{}'::jsonb,
    recargo_tarjeta jsonb not null default '{"aplica": false, "porcentaje": 0}'::jsonb,
    creado_por      uuid references usuarios (id),
    created_at      timestamptz not null default now()
);

create index locales_ubicacion_idx on locales using gist (ubicacion);

-- ------------------------------------------------------ productos_canonicos
create table productos_canonicos (
    id            uuid primary key default gen_random_uuid(),
    ean           text not null unique check (ean ~ '^[0-9]{8,14}$'),
    nombre        text not null,
    marca         text,
    tamano_valor  numeric check (tamano_valor > 0),
    tamano_unidad text check (tamano_unidad in ('g', 'kg', 'ml', 'l', 'u')),
    imagen_url    text,
    origen        text not null default 'manual' check (origen in ('off', 'manual')),
    created_at    timestamptz not null default now(),
    -- tamaño y unidad van juntos o ninguno
    check ((tamano_valor is null) = (tamano_unidad is null))
);

-- --------------------------------------------------------- items_genericos
-- Atados a un local. Modelados pero desactivados por config en v0.0.1.
create table items_genericos (
    id            uuid primary key default gen_random_uuid(),
    local_id      uuid not null references locales (id),
    categoria     text not null,
    descripcion   text not null,
    tamano_valor  numeric check (tamano_valor > 0),
    tamano_unidad text check (tamano_unidad in ('g', 'kg', 'ml', 'l', 'u')),
    created_at    timestamptz not null default now(),
    check ((tamano_valor is null) = (tamano_unidad is null))
);

-- ----------------------------------------------------------------- precios
create table precios (
    id                    uuid primary key default gen_random_uuid(),
    producto_canonico_id  uuid references productos_canonicos (id),
    item_generico_id      uuid references items_genericos (id),
    local_id              uuid not null references locales (id),
    precio                numeric(12, 2) not null check (precio > 0),
    fecha                 timestamptz not null default now(),
    user_id               uuid not null references usuarios (id),
    created_at            timestamptz not null default now(),
    -- un precio apunta a exactamente un tipo de producto
    check ((producto_canonico_id is null) <> (item_generico_id is null))
);

create index precios_canonico_local_fecha_idx
    on precios (producto_canonico_id, local_id, fecha desc);
create index precios_generico_fecha_idx
    on precios (item_generico_id, fecha desc);

-- ------------------------------------------------------------ validaciones
-- Modelada para después; la validación colaborativa NO está en v0.0.1.
create table validaciones (
    id         uuid primary key default gen_random_uuid(),
    precio_id  uuid not null references precios (id),
    user_id    uuid not null references usuarios (id),
    resultado  text not null check (resultado in ('ok', 'mal')),
    created_at timestamptz not null default now(),
    unique (precio_id, user_id)
);

-- ------------------------------------------------------------------ config
-- Tunables de admin. `rubro` null = valor global; con rubro = override.
create table config (
    clave  text not null,
    valor  jsonb not null,
    rubro  text
);

create unique index config_clave_rubro_idx on config (clave, coalesce(rubro, ''));
