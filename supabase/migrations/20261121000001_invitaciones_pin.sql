-- PINs de invitación de un solo uso, administrados desde el panel (docs/04 §6).
-- Un PIN es una invitación con usos_max = 1; «usado» = usos >= usos_max (se calcula,
-- no se guarda aparte). Acá solo se agrega el registro de CUÁNDO y POR QUIÉN se usó.

alter table invitaciones
    -- el id de auth (sub del JWT) de quien creó su usuario con este código; se cruza
    -- con usuarios.auth_id para mostrar el alias. Sin FK: el usuario se crea después.
    add column usada_por_auth uuid,
    add column usada_at       timestamptz,
    add column creada_por     uuid references usuarios (id);

-- Un uso gastado deja fecha; sin usos no hay fecha ni usuario.
alter table invitaciones
    add constraint invitaciones_uso_coherente
    check (usos > 0 or (usada_at is null and usada_por_auth is null));

-- El rastro de auditoría del panel acepta la entidad nueva.
alter table auditoria_admin drop constraint auditoria_admin_entidad_check;
alter table auditoria_admin add constraint auditoria_admin_entidad_check
    check (entidad in ('local', 'precio', 'config', 'producto', 'conflicto', 'usuario',
                       'invitacion'));
