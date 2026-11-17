-- Catálogo por fuentes (v0.0.2, corte 7). SQL plano, portable a cualquier Postgres.
-- Cada ETL (uno por fuente) escribe el dato crudo en `producto_fuentes` y el
-- catálogo canónico se arma desde ahí. Si dos fuentes discrepan, queda en
-- `conflictos_catalogo` para revisión manual. La lógica de integridad vive acá.

create extension if not exists pg_trgm;
create extension if not exists unaccent;

-- ------------------------------------------------------ productos_canonicos
-- Más fuentes de catálogo: se amplía el check de `origen`.
alter table productos_canonicos drop constraint productos_canonicos_origen_check;
alter table productos_canonicos
    add constraint productos_canonicos_origen_check
    check (origen in ('off', 'manual', 'sepa'));

-- Campos que el admin resolvió a mano: ningún ETL los vuelve a tocar.
-- Valores posibles: nombre, marca, tamano (valor + unidad juntos).
alter table productos_canonicos
    add column campos_bloqueados text[] not null default '{}'
    check (campos_bloqueados <@ array['nombre', 'marca', 'tamano']);

-- Un campo bloqueado solo se cambia dentro de una transacción que lo habilite
-- (la resolución de conflictos): select set_config('app.catalogo_write', 'on', true);
create function proteger_campos_bloqueados() returns trigger
language plpgsql as $$
begin
    if coalesce(current_setting('app.catalogo_write', true), '') = 'on' then
        return new;
    end if;
    if 'nombre' = any (old.campos_bloqueados) and new.nombre is distinct from old.nombre then
        raise exception 'nombre bloqueado por resolución manual';
    end if;
    if 'marca' = any (old.campos_bloqueados) and new.marca is distinct from old.marca then
        raise exception 'marca bloqueada por resolución manual';
    end if;
    if 'tamano' = any (old.campos_bloqueados)
       and (new.tamano_valor is distinct from old.tamano_valor
            or new.tamano_unidad is distinct from old.tamano_unidad) then
        raise exception 'tamaño bloqueado por resolución manual';
    end if;
    if new.campos_bloqueados is distinct from old.campos_bloqueados then
        raise exception 'campos_bloqueados solo se modifica al resolver un conflicto';
    end if;
    return new;
end;
$$;

create trigger productos_canonicos_proteger_bloqueados
    before update on productos_canonicos
    for each row execute function proteger_campos_bloqueados();

-- --------------------------------------------------------- producto_fuentes
-- Qué fuente aportó qué EAN y con qué datos. La clave (ean, fuente) también
-- sirve de índice por EAN.
create table producto_fuentes (
    ean         text not null check (ean ~ '^[0-9]{8,14}$'),
    fuente      text not null check (fuente in ('off', 'sepa')),
    datos       jsonb not null,
    cargado_en  timestamptz not null default now(),
    primary key (ean, fuente)
);

-- -------------------------------------------------------- conflictos_catalogo
-- A = lo que hay en el catálogo; B = lo que trae la fuente que discrepa.
create table conflictos_catalogo (
    id           uuid primary key default gen_random_uuid(),
    ean          text not null check (ean ~ '^[0-9]{8,14}$'),
    campo        text not null check (campo in ('nombre', 'marca', 'tamano')),
    valor_a      text not null,
    fuente_a     text not null check (fuente_a in ('off', 'manual', 'sepa')),
    valor_b      text not null,
    fuente_b     text not null check (fuente_b in ('off', 'sepa')),
    estado       text not null default 'pendiente' check (estado in ('pendiente', 'resuelto')),
    elegido      text check (elegido in ('a', 'b')),
    resuelto_por uuid references usuarios (id),
    resuelto_en  timestamptz,
    created_at   timestamptz not null default now(),
    -- el mismo desacuerdo no se vuelve a abrir (ni siquiera una vez resuelto)
    unique (ean, campo, fuente_a, valor_a, fuente_b, valor_b),
    check ((estado = 'resuelto') = (resuelto_en is not null and elegido is not null))
);

create index conflictos_catalogo_pendientes_idx
    on conflictos_catalogo (created_at) where estado = 'pendiente';

-- ------------------------------------------------------- funciones de apoyo
-- Prioridad de una fuente según config `catalogo_prioridad_fuentes` (array JSON,
-- de mayor a menor). Sin config: manual > sepa > off (SEPA es la fuente principal para Argentina). Desconocida: la última.
create function prioridad_fuente(p_fuente text) returns integer
language sql stable as $$
    select coalesce(
        (select ord::int
           from jsonb_array_elements_text(
                    coalesce((select valor from config
                               where clave = 'catalogo_prioridad_fuentes' and rubro is null),
                             '["manual", "sepa", "off"]'::jsonb)
                ) with ordinality as t(f, ord)
          where f = p_fuente),
        1000
    );
$$;

-- «Parecidos»: las diferencias de forma (mayúsculas, acentos, signos, «Aceite
-- Girasol» vs «aceite de girasol») no son conflicto; solo lo muy distinto.
create function textos_similares(a text, b text) returns boolean
language sql stable as $$
    with n as (
        select trim(regexp_replace(lower(unaccent(a)), '[^a-z0-9]+', ' ', 'g')) as x,
               trim(regexp_replace(lower(unaccent(b)), '[^a-z0-9]+', ' ', 'g')) as y
    )
    select x = y
        or similarity(x, y) >= 0.35
        or word_similarity(x, y) >= 0.7
        or word_similarity(y, x) >= 0.7
    from n;
$$;

-- Tamaño en la unidad base (g, ml o u) y su familia, para comparar sin importar
-- si una fuente dice «1 kg» y otra «1000 g».
create function tamano_base(valor numeric, unidad text) returns numeric
language sql immutable as $$
    select case unidad when 'kg' then valor * 1000 when 'l' then valor * 1000 else valor end;
$$;

create function tamano_familia(unidad text) returns text
language sql immutable as $$
    select case unidad when 'g' then 'masa' when 'kg' then 'masa'
                       when 'ml' then 'volumen' when 'l' then 'volumen'
                       when 'u' then 'unidad' end;
$$;

create function tamanos_equivalentes(v1 numeric, u1 text, v2 numeric, u2 text) returns boolean
language sql immutable as $$
    select tamano_familia(u1) = tamano_familia(u2)
       and abs(tamano_base(v1, u1) - tamano_base(v2, u2))
           <= 0.01 * greatest(tamano_base(v1, u1), tamano_base(v2, u2));
$$;
