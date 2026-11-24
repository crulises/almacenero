-- Corte 19a (docs/04 §11): una fila por cada vez que se usó una invitación, para poder dibujar la
-- serie «invitaciones aceptadas» en el dashboard. Hasta ahora `invitaciones.usada_at` /
-- `usada_por_auth` guardaban solo el ÚLTIMO uso (se pisaban): en un código de varios usos se perdía
-- el historial. SQL plano, portable a cualquier Postgres.

create table invitaciones_usos (
    id            bigint generated always as identity primary key,
    -- si el admin borra la invitación, el uso queda en la serie (la gente que entró, entró)
    invitacion_id uuid references invitaciones (id) on delete set null,
    -- el id de auth (sub del JWT) de quien creó su usuario; se completa después de gastar el uso
    auth_id       uuid,
    usada_en      timestamptz not null default now()
);

create index invitaciones_usos_usada_idx on invitaciones_usos (usada_en);
create index invitaciones_usos_invitacion_idx on invitaciones_usos (invitacion_id);

-- Los usos que ya existían: de cada invitación usada solo se conoce el último (los anteriores se
-- pisaron), así que entra una fila por invitación. Es lo más fiel que se puede reconstruir.
insert into invitaciones_usos (invitacion_id, auth_id, usada_en)
select id, usada_por_auth, usada_at from invitaciones where usos > 0 and usada_at is not null;

-- Solo el backend la toca; PostgREST (anon/authenticated) no tiene que verla.
alter table invitaciones_usos enable row level security;
