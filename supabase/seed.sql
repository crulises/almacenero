-- Seeds chicos para desarrollo. Idempotentes. Nada de datos grandes acá
-- (el catálogo real entra por el ETL de Open Food Facts).

-- Local del admin (v0.0.1 trabaja con un solo local). Ubicación de ejemplo
-- (Buenos Aires): reemplazar por la real.
insert into locales (id, nombre, direccion, ubicacion, medios_pago, verificado)
values (
    '00000000-0000-0000-0000-000000000001',
    'Local del admin',
    'Dirección a completar',
    st_setsrid(st_makepoint(-58.3816, -34.6037), 4326)::geography,
    '{"efectivo": true, "debito": true, "credito": true, "transferencia": true, "qr": true}',
    true
)
on conflict (id) do nothing;

-- Configuración inicial.
insert into config (clave, valor, rubro) values
    ('ventana_frescura_dias', '30',  null),
    ('umbral_verde_dias',     '7',   null),
    ('umbral_amarillo_dias',  '21',  null),
    ('pesables_habilitados',  'false', null),
    ('modo_acceso',           '"solo_invitacion"', null),
    ('geofence_metros',       '150', null),
    ('geofence_precision_max_m', '100', null),
    ('radio_precios_m',       '5000', null),
    ('karma_por_carga',       '1',   null),
    -- Alta de locales por cualquier usuario: solo mientras se prueba (Doc 1: la
    -- regla es que solo el admin crea locales). Con false, solo un admin.
    ('alta_locales_abierta',  'true', null),
    ('max_locales_por_dia',   '50',  null),
    ('local_duplicado_metros', '50', null),
    ('local_duplicado_similitud', '0.8', null),
    -- Anti-spam (docs/04 §6)
    -- Solo desarrollo: Docker Desktop le pone la MISMA IP (192.168.65.1) a todo lo que entra,
    -- así que el cupo por IP lo comparten el celular, el curl y los tests. En producción, 10.
    ('auth_altas_por_hora_ip',   '100', null),
    ('auth_refresh_por_hora_ip', '120', null),
    ('max_precios_por_hora',     '60',  null),
    ('max_precios_por_dia',      '300', null),
    -- Moderación (docs/04 §9)
    ('karma_umbral_aviso',       '-5',  null),
    ('karma_umbral_restriccion', '-15', null),
    -- Eventos de producto (docs/04 §11.2)
    ('eventos_max_filas',        '100000', null),
    ('max_lotes_eventos_por_hora', '120', null),
    -- Dashboard de admin (docs/04 §11)
    ('panel_zona_horaria',        '"America/Buenos_Aires"', null),
    ('dashboard_activo_dias',     '7', null)
on conflict do nothing;

-- Invitación de desarrollo (en producción se crea otra: `make invitacion`).
insert into invitaciones (codigo, nota)
values ('almacenero-dev', 'código de desarrollo')
on conflict (codigo) do nothing;

-- Un par de productos canónicos de ejemplo para probar el flujo de escaneo.
insert into productos_canonicos (ean, nombre, marca, tamano_valor, tamano_unidad, origen)
values
    ('7790070411112', 'Aceite de girasol', 'Ejemplo', 900, 'ml', 'manual'),
    ('7791234567890', 'Fideos tirabuzón',  'Ejemplo', 500, 'g',  'manual')
on conflict (ean) do nothing;
