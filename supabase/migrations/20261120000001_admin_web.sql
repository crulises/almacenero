-- Panel web de admin (v0.0.2, corte 11). SQL plano, portable a cualquier Postgres.

-- ---------------------------------------------------------------- usuarios
-- Anónimos y registrados. Los dos datos salen de los claims del JWT y el backend
-- los sincroniza en cada request (`app/auth.py`):
--   email           null para anónimos.
--   es_anonimo      true mientras la cuenta no se ligó a un email o red social.
--   anonimo_auth_id el id de auth con el que el usuario empezó como anónimo (Doc 1,
--                   «Identidad»: al ligarse, el anónimo se atribuye a la persona real).
--                   null para quien nació registrado (p. ej. un admin creado por mail).
--                   Con GoTrue, ligar un anónimo conserva su id, así que coincide con
--                   `auth_id`; la columna deja la asociación explícita por si algún día
--                   un registrado pasa a tener otro id.
alter table usuarios
    add column email           text,
    add column es_anonimo      boolean not null default true,
    add column anonimo_auth_id uuid;

update usuarios set anonimo_auth_id = auth_id;

create unique index usuarios_email_idx on usuarios (lower(email)) where email is not null;

-- -------------------------------------------------------- auditoria_admin
-- Toda corrección hecha desde el panel deja una fila (quién, qué, cuándo, antes y
-- después). Solo se agrega: ni el backend puede modificarla ni borrarla.
create table auditoria_admin (
    id          uuid primary key default gen_random_uuid(),
    usuario_id  uuid references usuarios (id),
    accion      text not null check (length(accion) between 1 and 60),
    entidad     text not null check (entidad in
                    ('local', 'precio', 'config', 'producto', 'conflicto', 'usuario')),
    entidad_id  text not null,
    antes       jsonb,
    despues     jsonb,
    nota        text,
    created_at  timestamptz not null default now()
);

create index auditoria_admin_fecha_idx on auditoria_admin (created_at desc);
create index auditoria_admin_entidad_idx on auditoria_admin (entidad, entidad_id);

create function auditoria_solo_agregar() returns trigger
language plpgsql as $$
begin
    raise exception 'auditoria_admin es solo de lectura: no se modifica ni se borra';
end;
$$;

create trigger auditoria_admin_solo_agregar
    before update or delete on auditoria_admin
    for each row execute function auditoria_solo_agregar();
