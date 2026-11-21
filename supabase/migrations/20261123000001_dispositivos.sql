-- Corte 12: dispositivo de cada cuenta (docs/04 §9, «Dispositivo»).
-- Solo el hash del ANDROID_ID, nunca el valor en claro. Sin FK a usuarios: en el alta
-- la cuenta del proveedor de auth existe antes que la fila de `usuarios`.

create table dispositivos (
    hash        text        not null check (hash ~ '^[0-9a-f]{64}$'),
    auth_id     uuid        not null,
    primera_vez timestamptz not null default now(),
    ultima_vez  timestamptz not null default now(),
    primary key (hash, auth_id)
);

create index dispositivos_auth_idx on dispositivos (auth_id);
