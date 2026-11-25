-- Cambio de alias (docs/superpowers/specs/2026-11-25-alias-editable-design.md).
-- El alias es un atributo del PERFIL (usuarios.id), no de la identidad del proveedor de auth:
-- sobrevive a asociar el usuario anónimo con un email o con Google/Apple.

-- ------------------------------------------------------ usuarios_alias_historial
-- Todos los alias que tuvo cada usuario, en orden. Solo se agrega (como auditoria_admin).
create table usuarios_alias_historial (
    id             uuid primary key default gen_random_uuid(),
    -- Sin foreign keys a propósito (igual que `eventos`): si algún día se borra un perfil, su
    -- rastro de alias queda; la trazabilidad no depende de que la fila de `usuarios` siga viva.
    usuario_id     uuid not null,
    alias_anterior text,                         -- null en el alta (primer alias)
    alias_nuevo    text not null check (length(alias_nuevo) between 1 and 50),
    cambiado_en    timestamptz not null default now(),   -- UTC (Doc 2, «Tiempo y zona horaria»)
    -- Quién lo cambió: el propio usuario, un admin, o null (el alta / el sistema).
    cambiado_por   uuid,
    origen         text not null check (origen in ('alta', 'usuario', 'admin', 'sistema')),
    check (alias_anterior is distinct from alias_nuevo)
);

create index usuarios_alias_historial_usuario_idx
    on usuarios_alias_historial (usuario_id, cambiado_en desc);
-- Para contar los cambios hechos por una persona en la última ventana (tope diario).
create index usuarios_alias_historial_actor_idx
    on usuarios_alias_historial (cambiado_por, cambiado_en desc) where origen = 'usuario';

create function alias_historial_solo_agregar() returns trigger
language plpgsql as $$
begin
    raise exception 'usuarios_alias_historial es solo de lectura: no se modifica ni se borra';
end;
$$;

create trigger usuarios_alias_historial_solo_agregar
    before update or delete on usuarios_alias_historial
    for each row execute function alias_historial_solo_agregar();

-- --------------------------------------------------------------- el trigger
-- Ningún camino (app, panel, make admin-crear, alta perezosa) cambia el alias sin dejar rastro.
-- El backend dice quién y por qué dentro de su transacción:
--   select set_config('app.alias_actor', '<uuid de usuarios>', true);
--   select set_config('app.alias_origen', 'usuario' | 'admin', true);
-- Sin eso queda origen 'sistema' (o 'alta' en el INSERT) y sin autor.
create function registrar_alias() returns trigger
language plpgsql as $$
declare
    actor  text := nullif(current_setting('app.alias_actor', true), '');
    origen text := nullif(current_setting('app.alias_origen', true), '');
begin
    if tg_op = 'INSERT' then
        insert into usuarios_alias_historial (usuario_id, alias_anterior, alias_nuevo, origen)
        values (new.id, null, new.alias, 'alta');
    elsif new.alias is distinct from old.alias then
        insert into usuarios_alias_historial
            (usuario_id, alias_anterior, alias_nuevo, cambiado_por, origen)
        values (new.id, old.alias, new.alias, actor::uuid, coalesce(origen, 'sistema'));
    end if;
    return null;
end;
$$;

create trigger usuarios_registrar_alias
    after insert or update of alias on usuarios
    for each row execute function registrar_alias();

-- Los usuarios que ya existían: su fila de alta (con el instante en que se crearon).
insert into usuarios_alias_historial (usuario_id, alias_anterior, alias_nuevo, cambiado_en, origen)
select id, null, alias, created_at, 'alta' from usuarios;

-- --------------------------------------------------------------- unicidad
-- Antes del índice: si ya había alias repetidos (el panel permitía cualquiera), el más viejo se
-- queda con el nombre y los demás reciben un sufijo con el comienzo de su id. El trigger lo anota
-- en el historial como cambio del sistema.
update usuarios u set alias = left(u.alias, 43) || '-' || left(u.id::text, 6)
from (
    select id, row_number() over (partition by lower(alias) order by created_at, id) as n
    from usuarios where alias !~* '^anon-'
) d
where d.id = u.id and d.n > 1;

-- Un alias vigente es de una sola persona, sin distinguir mayúsculas. Los `anon-XXXXXX` quedan
-- afuera: se derivan de 6 hex del auth_id y una colisión no puede romper el alta perezosa
-- (el backend además no deja elegirlos: «anon-» es un prefijo reservado).
create unique index usuarios_alias_unico_idx
    on usuarios (lower(alias)) where alias !~* '^anon-';
