-- Corte 18 (mejora): resolver un conflicto del catálogo editando los datos a mano.
-- Hasta ahora un conflicto se resolvía eligiendo A (lo del catálogo) o B (lo de la otra fuente);
-- si ninguna de las dos estaba bien, no había salida. `elegido = 'manual'` significa «ninguna:
-- una persona corrigió el producto y con eso se cerró la disputa». Idempotente.

alter table conflictos_catalogo drop constraint if exists conflictos_catalogo_elegido_check;
alter table conflictos_catalogo
    add constraint conflictos_catalogo_elegido_check check (elegido in ('a', 'b', 'manual'));
