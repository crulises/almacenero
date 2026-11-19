-- Datos de DEMO para ver el mapa y la frescura (NO es el seed de arranque).
-- Idempotente: se puede correr de nuevo y vuelve a dejar lo mismo.
-- Se borra con `make demo-borrar`. Todo lo de demo lleva el prefijo `demo-`.
-- Se ubica alrededor de (:lat, :lng): `make demo LAT=-25.92 LNG=-54.57`.

delete from precios where local_id in (select id from locales where nombre like 'demo-%');
delete from locales where nombre like 'demo-%';

-- Un usuario de demo para atribuir los precios (sin karma).
insert into usuarios (auth_id, alias)
values ('00000000-0000-0000-0000-00000000de40', 'demo-usuario')
on conflict (auth_id) do nothing;

insert into locales (nombre, direccion, ubicacion, verificado) values
    ('demo-Almacén Don Pepe',   'Calle 1', st_setsrid(st_makepoint(:lng + 0.0030, :lat + 0.0020), 4326)::geography, true),
    ('demo-Super Chino Ahorro', 'Calle 2', st_setsrid(st_makepoint(:lng - 0.0040, :lat - 0.0030), 4326)::geography, true),
    ('demo-Kiosco Esquina',     'Calle 3', st_setsrid(st_makepoint(:lng + 0.0010, :lat - 0.0040), 4326)::geography, false);

-- Aceite de girasol (del seed) con precios de distinta antigüedad: verde, amarillo, rojo.
insert into precios (producto_canonico_id, local_id, precio, user_id, fecha)
select pc.id, l.id, v.precio, u.id, now() - make_interval(days => v.dias)
from (values
    ('demo-Almacén Don Pepe',   1890.00,  2),
    ('demo-Super Chino Ahorro', 1650.00, 12),
    ('demo-Kiosco Esquina',     2100.00, 40)
) v(nombre, precio, dias)
join locales l on l.nombre = v.nombre
cross join (select id from productos_canonicos where ean = '7790070411112') pc
cross join (select id from usuarios where alias = 'demo-usuario') u;
