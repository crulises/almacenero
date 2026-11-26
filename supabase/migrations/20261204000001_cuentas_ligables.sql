-- Corte 21: cuentas ligables (docs/superpowers/specs/2026-11-26-cuentas-ligables-design.md).
-- Estado nuevo `fusionada`: una cuenta huérfana (anónima) que el admin reclamó para una cuenta
-- ligada. No es `baja` a propósito: la baja marca el dispositivo (docs/04 §9) y bloquearía altas
-- legítimas en ese celular. La escritura del estado sigue protegida por `proteger_estado`
-- (solo con `app.estado_write = on`, dentro de la transacción del panel).

alter table usuarios drop constraint usuarios_estado_check;
alter table usuarios
    add constraint usuarios_estado_check check (estado in ('activo', 'baja', 'fusionada')),
    add column fusionada_en uuid references usuarios (id);

-- Fusionada con destino (distinto de ella misma); activa o de baja, sin destino.
alter table usuarios
    add constraint usuarios_fusionada_coherente
    check ((estado = 'fusionada') = (fusionada_en is not null) and fusionada_en is distinct from id);

-- `proteger_estado` mira `estado` y `baja_at`; `fusionada_en` solo cambia junto con el estado,
-- así que queda cubierta por el mismo trigger y el check de arriba.
