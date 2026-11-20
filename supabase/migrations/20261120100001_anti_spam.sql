-- Corte 9: anti-spam (docs/04 §6). Invitaciones para `modo_acceso = solo_invitacion`.

create table invitaciones (
    id          uuid primary key default gen_random_uuid(),
    -- Siempre normalizado (minúsculas, sin espacios en los bordes): la base lo exige,
    -- así «ABC » y «abc» son el mismo código y no hay duplicados disfrazados.
    codigo      text not null unique check (codigo = lower(btrim(codigo)) and codigo <> ''),
    usos_max    integer check (usos_max > 0),            -- null = sin tope
    usos        integer not null default 0 check (usos >= 0),
    vence       timestamptz,                             -- null = no vence
    nota        text,
    created_at  timestamptz not null default now(),
    -- el contador nunca pasa del tope, ni con requests concurrentes
    check (usos_max is null or usos <= usos_max)
);

-- Para contar las cargas de un usuario en la última hora / el último día.
create index if not exists precios_user_created_idx on precios (user_id, created_at desc);
