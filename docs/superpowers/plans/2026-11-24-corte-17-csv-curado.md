# Corte 17 – CSV curado por línea de comandos: plan de implementación

> **Para agentes:** usar superpowers:subagent-driven-development o superpowers:executing-plans. Los pasos usan `- [ ]`.

**Meta:** exportar desde las fuentes crudas (OFF, SEPA) un CSV curado reproducible e importarlo
al catálogo con validación en seco, dejando registro (hash + versión) para poder reconstruirlo y borrar el archivo.

**Arquitectura:** paquete `etl/curado/` (formato, exportar, importar). El importador reutiliza
`fusionar_lote` con `fuente='curado'`; la validación en seco corre ese mismo camino dentro de una
transacción que se revierte, así que el reporte nunca diverge de la importación real.

**Stack:** Python 3.12, asyncpg, pytest contra Postgres local real (Supabase CLI), SQL plano.

**Spec:** `docs/04-plan-v0.0.2.md` §10-B (+ refinamientos en esta carpeta, ver §Decisiones del Doc 4 al cerrar el corte).

## Restricciones globales

- Integridad en Postgres, negocio en Python; migración SQL plana.
- EAN de prueba con prefijo `79999` (se limpian antes/después de cada test).
- `make lint` y `make test` verdes; el CI solo llama a targets del Makefile.
- Prioridad de fuentes: `manual > curado > sepa > off`.
- Formato `catalogo_curado_v1`, columnas: `ean, nombre, marca, tamano_valor, tamano_unidad, pack_cantidad, presentacion, imagen_url, fuente_origen, nota`.

## Foco de revisión (entradas que el spec no menciona)

- CSV con BOM, `\r\n`, `.gz` y comillas con comas/saltos de línea dentro del nombre.
- EAN duplicado dentro del archivo (se queda el último y se informa).
- Fila con tamaño sin unidad (o al revés), unidad no permitida, `pack_cantidad` < 2.
- Archivo editado a mano (el hash del contenido no coincide con el declarado).
- Re-importar el mismo archivo (idempotente, avisa "ya importado").
- Producto con campos bloqueados por un admin (no se pisan) y de origen `manual` (no cambia el origen).

---

### Tarea 1: Migración (fuente `curado`, prioridad, `catalogo_lotes`)

**Files:** Create `supabase/migrations/20261127000001_catalogo_curado.sql`; Test `backend/tests/test_integridad.py` (o `etl/tests/test_curado_db.py`).

**Produce:** checks de `productos_canonicos.origen`, `producto_fuentes.fuente`, `conflictos_catalogo.fuente_a/fuente_b` aceptan `curado`; `prioridad_fuente()` con default `["manual","curado","sepa","off"]` (y `curado` va aunque la config guardada no lo traiga); tabla `catalogo_lotes(id uuid, formato, version_normalizador int, nombre_archivo, sha256, sha256_declarado, filas, nuevos, cambiados, iguales, invalidos, fuentes_entrada jsonb, subido_por uuid null, etl_ejecucion_id uuid null, creado_en)`; `unique (sha256, version_normalizador, creado_en)` no: solo índice por `sha256`.

- [ ] Test: `prioridad_fuente('curado') < prioridad_fuente('sepa')` y `> prioridad_fuente('manual')`; insertar `origen='curado'` y `producto_fuentes.fuente='curado'` no falla; `catalogo_lotes` rechaza `sha256` que no sea 64 hex.
- [ ] Ver que falla, escribir la migración, `make migrate`, ver que pasa.
- [ ] Commit.

### Tarea 2: Formato (`etl/curado/formato.py`)

**Interfaces – produce:**
`COLUMNAS: tuple[str, ...]`, `FORMATO = "catalogo_curado_v1"`;
`class FilaInvalida(Exception)` con `.motivo: str`;
`fila_a_producto(fila: dict[str, str], fuente_origen_default: str = "curado") -> Producto` (valida EAN con `normalizar_ean`, nombre ≥ 2, tamaño valor+unidad juntos con unidad en `g kg ml l u`, `pack_cantidad` ≥ 2 o vacío, `presentacion` ≤ 40; arma `datos` JSON con `fuente_origen` y `nota`);
`producto_a_fila(p: Producto, fuente_origen: str, nota: str = "") -> dict[str, str]`;
`escribir(ruta, filas, cabecera: dict) -> str` (devuelve `sha256` del contenido; `.gz` si la ruta termina en `.gz`; salida determinista: ordenada por EAN, `\n`);
`leer(ruta) -> tuple[dict[str,str], Iterator[tuple[int, dict[str,str]]], Callable[[], str]]` (cabecera de comentarios, filas con su número de línea, y un cierre que da el `sha256` real del contenido tras recorrer; tolera BOM, `\r\n`, `.gz`).

- [ ] Tests: ida y vuelta (`escribir` → `leer`) conserva filas; el hash no depende de `# generado`; BOM/CRLF/gz; cada motivo de `FilaInvalida` (`ean_formato`, `nombre_corto`, `tamano_incompleto`, `unidad_invalida`, `pack_invalido`).
- [ ] Implementar; pasar; commit.

### Tarea 3: Exportador (`etl/curado/exportar.py`, `python -m etl.curado.exportar`)

**Interfaces:** `exportar(salida: Path, off: Path | None, sepa: list[Path], paises: frozenset[str] | None, sepa_min_filas: int = 1) -> dict` (devuelve cabecera con `formato, generado, normalizador, fuentes, filas, sha256`). Sin base de datos.

- Lee OFF con `etl.off.__main__.filas/transformar` y SEPA con `Agrupador`; normaliza cada fila (`normalizar_producto`); por EAN toma la fila de mayor prioridad (`sepa` > `off`) y completa vacíos (marca, tamaño valor+unidad juntos, imagen, presentación, pack) con la otra; `fuente_origen` = `sepa`, `off` o `sepa+off`; normaliza de nuevo el resultado (punto fijo).
- Cabecera: `# formato`, `# generado`, `# normalizador: <NORMALIZADOR_VERSION>`, `# fuentes: <nombre>:<sha256>:<bytes>` (una por archivo de entrada), `# contenido_sha256`.

- [ ] Test: genera un OFF mínimo + un zip SEPA mínimo (en `tmp_path`), exporta dos veces → mismo `sha256` de contenido; EAN en ambas fuentes gana SEPA y completa con OFF; filtro `paises`; `sepa_min_filas` filtra; cada fila de salida es punto fijo de `normalizar_producto`.
- [ ] Implementar; pasar; commit.

### Tarea 4: Importador (`etl/curado/importar.py`, `python -m etl.curado.importar ARCHIVO [--aplicar] [--forzar]`)

**Interfaces:** `importar(ruta: Path, aplicar: bool, forzar: bool = False, subido_por: UUID | None = None, etl_ejecucion_id: UUID | None = None, conn=None, lote: int = 20_000, al_lote: Callable | None = None) -> ReporteImport` con `ReporteImport(leidas, validas, invalidas: Counter, ejemplos_invalidos: list[tuple[int,str,str]], nuevos, cambiados, iguales, ejemplos_cambios: list[dict], duplicados, editado: bool, ya_importado: UUID | None, lote_id: UUID | None, sha256, texto())`.

- Valida fila a fila (formato.py); EAN repetido → gana la última, cuenta `duplicado_en_archivo`.
- Por lote: foto previa de los EAN (`select` de campos) → `fusionar_lote(conn, 'curado', ...)` → foto posterior; `nuevos` = no existían, `cambiados` = alguna columna distinta, `iguales` = resto; guarda hasta 20 ejemplos de cambios (campo antes→después).
- Simulacro (`aplicar=False`): cada lote dentro de `conn.transaction()` que se revierte (se lanza una excepción propia). Aplicar: commit por lote y al final inserta la fila de `catalogo_lotes` (hash real, hash declarado, versión, fuentes_entrada de la cabecera, conteos).
- Mismo `sha256` + misma `NORMALIZADOR_VERSION` ya registrado → `ya_importado`; sin `forzar` no escribe nada.
- Respeta bloqueados (lo hace `fusionar_lote`/trigger): test explícito.

- [ ] Tests contra Postgres: simulacro no deja rastro (cuentas y `catalogo_lotes` iguales) pero informa lo correcto; aplicar inserta con `origen='curado'`, `producto_fuentes.fuente='curado'` con `datos` ⊇ `fuente_origen`, `archivo_sha256`; segunda importación = `ya_importado`; con `forzar` todo "iguales"; campo bloqueado no cambia; producto `manual` no cambia de origen; inválidas con motivo y número de línea; archivo editado → `editado=True`; round-trip con el exportador (Tarea 3) deja `iguales == validas` al reimportar.
- [ ] Implementar; pasar; commit.

### Tarea 5: Makefile, docs, CLAUDE.md, verificación con datos reales

- [ ] Targets `catalogo-csv-exportar` (`SALIDA=`, `OFF_ARCHIVO`, `SEPA_ARCHIVOS`, `OFF_PAISES`, `SEPA_MIN_FILAS`) y `catalogo-csv-importar ARCHIVO=... [APLICAR=1] [FORZAR=1]`; agregarlos a `.PHONY`.
- [ ] Probar a mano con el zip de SEPA local y `make etl-off-muestra` (30 MB, autorizado): exportar, simulacro, aplicar sobre la base local, reimportar (iguales).
- [ ] Documentar: `docs/04` §10-B (estado + refinamientos), `docs/07` (curado), `docs/05` (fuente curado), `docs/03` (Síntoma→Causa→Solución de lo que aparezca), `etl/README.md`, `CLAUDE.md`.
- [ ] `make lint` + `make test` (salvo Flutter si no corre), commit, push, PR a `main`.
