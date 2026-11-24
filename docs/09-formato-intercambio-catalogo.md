# Doc 9 — Formato de intercambio de catálogos (`catalogo_curado_v1` / `v2`)

> Este documento es **autocontenido a propósito**: el mismo formato se va a usar para intercambiar
> catálogos con otro proyecto. Quien lo implemente allá no necesita leer el resto del repo.
> Implementación de referencia: `etl/curado/` (`formato.py`, `exportar.py`, `exportar_base.py`,
> `importar.py`, `leeme.py`), `etl/comun/paquete.py` (el `.zip`) y `etl/locales_intercambio.py`
> (locales, §8). Tests que fijan el comportamiento: `etl/tests/test_curado_*.py`,
> `test_paquete.py`, `test_locales_intercambio.py`.

## 1. Para qué sirve y qué decisiones lo definen

Un archivo de intercambio es **el catálogo con su historia de tratamiento**: no solo «qué
producto es», también «qué le hicimos». Las decisiones (tomadas el 2026-11-24, corte 18):

1. **Un solo archivo.** El contenido es un CSV UTF-8 (legible en cualquier planilla). Lo que se
   **exporta** es un paquete `.zip` con ese CSV y un `LEEME.txt` que cuenta qué es, qué se hizo y
   qué reglas del normalizador se aplicaron (§2.1). Sin base de datos adjunta. Quien exporta **no
   elige formato ni extensión**: solo pone un nombre.
2. **Lleva todos los metadatos que importan de cada registro** (origen, bloqueos humanos, si lo
   cargó o revisó una persona, sugerencias, avisos del normalizador, conflictos), para que al
   importarlo **no se repita el trabajo manual** ni se vuelva a pelear lo ya resuelto.
3. **Los metadatos son conteos y banderas, nunca personas.** No viajan ids de usuarios, correos ni
   ids internos de la base. Se puede compartir el archivo sin filtrar quién hizo qué.
4. **Re-importable sin sorpresas.** Exportar e importar en la misma base no cambia nada; importar
   en otra base reproduce lo que importa (§5). Un importador que no entienda el v2 puede leer
   solo las columnas del v1 e ignorar el resto.
5. **Reproducible y verificable.** El `sha256` es del **contenido** (§4): dos exportaciones del
   mismo estado dan el mismo hash, y si alguien edita el archivo a mano se nota.
6. **No se confía en la calidad de otro.** `calidad`, `estado_calidad` y `calidad_motivos` viajan
   como información, pero quien importa **recalcula** con su normalizador.
7. **Versionado por la cabecera, no por el nombre del archivo.** Se agregan columnas al final sin
   romper a los lectores viejos; un cambio incompatible sube de versión (`v3`).

## 2. Forma del archivo

```
# formato: catalogo_curado_v2
# generado: 2026-11-24T17:54:33Z
# normalizador: 1
# fuentes: (base de datos)
# exportado_de: catalogo
# contenido_sha256: 92457a8d…
ean,nombre,marca,tamano_valor,…
00000086,Vegan protein powder,…
```

- Primero, líneas de comentario `# clave: valor` (la clave termina en el primer `:`). Después, la
  fila de nombres de columna y una fila por producto, ordenadas por `ean`.
- CSV estándar (RFC 4180): separador `,`, comillas dobles para campos con coma, comilla o salto
  de línea. Al escribir: `\n`, sin BOM. Al leer se toleran BOM, `\r\n` y `.gz`.
- Cabecera: `formato` es obligatoria (`catalogo_curado_v1` o `catalogo_curado_v2`); el resto es
  informativo: `generado` (UTC), `normalizador` (versión del normalizador de quien exportó),
  `fuentes` (`nombre:sha256` de cada archivo crudo, o `(base de datos)`), `exportado_de`,
  `paises`, `sepa_min_filas`, `contenido_sha256`.
- Clave única: `ean`. Si se repite dentro del archivo, **gana la última** y se informa.

### 2.1 El paquete `.zip` y cómo se reconoce un archivo

Lo que sale de un export es `<nombre>.zip` con **dos** archivos: `<nombre>.csv` (lo de arriba) y
`LEEME.txt` (texto para personas, no lo lee ninguna máquina). El `LEEME.txt` dice: qué es el
archivo, de dónde salió, el hash, cuántos productos tienen cada tratamiento, **qué reglas del
normalizador se aplicaron** (a cuántos productos y con un ejemplo antes → después), por qué algunos
productos no llegan al puntaje máximo, las columnas y cómo importarlo.

Al **importar**, el formato se reconoce por el **contenido** (los primeros bytes: `PK` = zip,
`1f 8b` = gzip, otra cosa = CSV), nunca por la extensión: quien sube el archivo no tiene que
acordarse cómo se llamaba. Un `.zip` tiene que tener **un solo** `.csv` (el `LEEME.txt` y lo demás
se ignoran); se rechazan los que se descomprimen a más de 2 GiB. El hash (§4) es del contenido del
CSV: es el mismo dentro de un zip, de un `.gz` o pelado.

## 3. Columnas

### 3.1 Datos del producto (v1 y v2)

| Columna | Obligatoria | Regla |
|---|---|---|
| `ean` | sí | 8 a 14 dígitos; los de 12 se completan con un 0 (EAN-13). Dígito verificador GS1 válido, salvo los `origen = manual` de un v2 (§5.3). Los que empiezan con 2 (balanza) se rechazan. |
| `nombre` | sí | 2 a 200 caracteres. |
| `marca` | no | hasta 100 caracteres. |
| `tamano_valor`, `tamano_unidad` | no, **juntos** | valor decimal > 0 (punto decimal) y unidad en `g kg ml l u`. |
| `pack_cantidad` | no | entero ≥ 2 (un «pack de 1» no es un pack: se deja vacío). |
| `presentacion` | no | hasta 40 caracteres, minúsculas (`botella`, `lata`…). |
| `imagen_url` | no | URL. |
| `fuente_origen` | no | de dónde salió el dato: `sepa`, `off`, `sepa+off`, `manual`… (texto libre informativo). |
| `nota` | no | texto libre. |

### 3.2 Metadatos del tratamiento (solo v2)

Las columnas van **al final**, en este orden. Una celda vacía = «no se sabe / no aplica».

| Columna | Valores | ¿Se restaura al importar? |
|---|---|---|
| `origen` | `off`, `sepa`, `curado`, `manual`: quién aportó el dato base del producto. | **Sí** (§5). |
| `campos_bloqueados` | subconjunto de `nombre`, `marca`, `tamano`, `presentacion`, separado por `\|`. Los que una persona fijó a mano y ningún ETL debe pisar. `tamano` cubre valor, unidad y pack. | **Sí** (§5). |
| `calidad` | 0–100 | No: informativa. |
| `estado_calidad` | `completo`, `parcial`, `dudoso`, `descartado` | No: se recalcula. |
| `calidad_motivos` | ids de motivo separados por `\|` | No: se recalcula. |
| `normalizador_version` | entero: versión del normalizador que lo evaluó por última vez («ya fue procesado por la v N») | No: informativa. |
| `cargado_a_mano` | `1`/`0`: lo dio de alta o corrigió una persona (origen `manual`, correcciones del panel o sugerencias aprobadas). | No: informativa. |
| `revisado` | `1`/`0`: lo tocó o validó una persona de cualquier forma (lo anterior, campos bloqueados, sugerencias rechazadas o conflictos resueltos). | No: informativa. |
| `ediciones_admin` | entero: altas y correcciones directas del panel. | No. |
| `sugerencias_aprobadas`, `sugerencias_rechazadas`, `sugerencias_pendientes` | enteros: sugerencias de moderadores/usuarios sobre este producto. | No. |
| `avisos_normalizador` | entero: veces que el normalizador ajustó un dato cargado por una persona y se le avisó. | No. |
| `conflictos_resueltos`, `conflictos_pendientes` | enteros: disputas entre fuentes (A vs B vs edición manual). | No. |

Lo «no restaurado» **no se pierde**: al importar queda guardado tal cual en
`producto_fuentes.datos.intercambio` (fuente `curado`) del producto, junto con el `origen` y los
`campos_bloqueados` del archivo. Así otro proyecto puede consultar la historia aunque su propio
sistema no tenga esas tablas.

> Lo que **no** exporta el formato: precios, locales, usuarios, karma, el dato crudo de cada
> fuente (`producto_fuentes`) ni el texto de sugerencias/avisos. Son datos del proyecto, no del
> catálogo.

## 4. Hash del contenido

`contenido_sha256` = SHA-256 (hex) de UTF-8 de: la fila de nombres de columna + todas las filas
de datos, ordenadas por `ean`, con `\n`, sin BOM y **sin las líneas `#`**. Por eso no cambia con
`# generado`, con la compresión ni con `\r\n`. Si el hash calculado al leer no coincide con el
declarado, el archivo fue editado a mano: se informa y (por defecto) se importa igual.

## 5. Cómo se importa (reglas de convergencia)

Importar es la misma fusión que cualquier carga de catálogo (con `fuente = 'curado'`), más la
restauración de los metadatos de un v2. Todo se puede **simular** antes (no escribe) y el reporte
no puede diferir de la importación real.

1. **Datos.** Prioridad entre fuentes `manual > curado > sepa > off`. Lo cargado a mano y los
   campos bloqueados **de quien importa** no se pisan.
2. **Origen.** El `origen` del archivo se restaura (para que la ida y vuelta sea fiel y no todo
   quede como `curado`). Nunca se degrada un `manual` local: si acá ya es `manual` y el archivo
   dice otra cosa, sigue `manual`.
3. **Trabajo humano del archivo.** Para cada campo en `campos_bloqueados` del archivo que **acá
   no** esté bloqueado: se aplica el valor del archivo (una persona lo fijó allá: vale más que el
   dato de un ETL) y el campo queda bloqueado acá también. Un `manual` del archivo vuelve como
   `manual`. Si acá ya estaba bloqueado, gana lo de acá.
4. **EAN confiable.** Una fila v2 con `origen = manual` no se rechaza por dígito verificador
   inválido: el catálogo de origen ya la aceptó (puede ser un código interno o de prueba). Se
   exige solo el largo. Cualquier otra fila sí pasa por la validación completa.
5. **Calidad.** Se recalcula siempre con el normalizador local (decisión 6).
6. **Idempotencia.** Importar de nuevo el mismo contenido con la misma versión del normalizador
   no hace nada (se avisa) salvo que se fuerce. Re-importar lo exportado de la misma base da «sin
   cambios» (probado con el catálogo completo: 134 506 filas, 0 cambios, 0 cambios de origen).
7. **Registro.** Cada importación aplicada deja una fila en `catalogo_lotes` (formato, hash,
   versión del normalizador, conteos, hash de las fuentes de entrada). El archivo no se guarda: se
   puede borrar.

Filas inválidas: no se importan y se informan con **número de línea y motivo** estable
(`ean_largo_invalido`, `ean_digito_verificador`, `nombre_corto`, `tamano_incompleto`,
`unidad_invalida`, `pack_invalido`, `origen_invalido`, `bloqueo_invalido`, `meta_invalida`…). El
resto del archivo sigue.

## 6. Cómo se genera

| Qué | Comando | Formato |
|---|---|---|
| Armar desde las **fuentes crudas** (OFF, SEPA), sin tocar la base | `make catalogo-csv-exportar` | v1 (no hay metadatos de tratamiento que llevar) |
| Volcar **el catálogo de la base** con todos sus metadatos | `make catalogo-csv-exportar-base` | v2 |
| Lo mismo desde el panel (ETL → «Armar el CSV curado» / «Exportar el catálogo») | worker local | v1 / v2 |
| Importar (cualquiera de los dos) | `make catalogo-csv-importar ARCHIVO=… [APLICAR=1]` | lee v1 y v2 |

**Cómo se nombra lo que se exporta:** los formularios y comandos piden **solo un nombre** (letras,
números, `.`, `-`, `_`; sin carpeta ni espacios), **sin extensión**: el sistema agrega `.zip`. Si
alguien igual escribe `.zip`, `.csv` o `.csv.gz`, se ignora. La carpeta la fija quien opera la
máquina: `ETL_EXPORT_DIR` (por defecto `etl/data/exports/`, fuera de git). Una ruta o un `..` se
rechazan: desde un formulario no se puede escribir en cualquier lado. Si ya había un export con ese
nombre, se reemplaza.

**Cómo se sube lo que se importa (panel):** el formulario tiene un selector de archivo
(`<input type="file">`); al elegirlo el panel lo sube al servidor (`POST /v1/admin/etl/archivos`, hasta
25 MB, guardado temporalmente en la base) y recién después se ejecuta el ETL con el id del archivo
subido. El simulacro lo deja disponible para confirmar; se borra al importar de verdad o a las 24 h.
Los volcados enormes de OFF/SEPA/OSM no se suben así: se leen de la máquina del worker.

## 7. Implementar el formato en otro proyecto (mínimo)

1. Leer las líneas `#` hasta la primera que no lo sea; exigir `formato ∈ {v1, v2}`.
2. Leer el resto como CSV con encabezado; **ignorar columnas desconocidas** (así un v3 con
   columnas nuevas al final sigue siendo legible).
3. Validar cada fila según §3.1; rechazar y reportar, no abortar.
4. Para un v2: guardar `origen` y `campos_bloqueados`, aplicar §5.2–5.3, y conservar el resto de
   los metadatos donde convenga (en este proyecto, `producto_fuentes.datos.intercambio`).
5. Al exportar: `\n`, sin BOM, filas por `ean`, hash según §4, `# formato` primero. Empaquetar en
   `.zip` con un `LEEME.txt` (§2.1) es recomendable; al importar, reconocer zip/gzip/CSV por los
   primeros bytes.

Cambios futuros: columnas nuevas **al final** y sin cambiar el significado de las existentes
(v2 sigue válido); cualquier cambio de significado o de forma = `v3`.

## 8. Locales (`locales_intercambio_v1`)

Los **locales validados** también se pueden llevar de una instalación a otra con el mismo criterio
(un archivo, sin personas, simulacro antes de escribir), **sin** el «modo migración de plataforma».
Implementación: `etl/locales_intercambio.py`. Comandos: `make locales-exportar [TODOS=1]` y
`make locales-importar ARCHIVO=… [APLICAR=1]`; en el panel, ETL → «Exportar locales» (worker local) e
«Importar locales» (con selector de archivo).

**Contenedor y nombre:** igual que el catálogo (§2.1 y §6): `.zip` con `<nombre>.csv` + `LEEME.txt`.

**Archivo:** cabecera `# formato: locales_intercambio_v1`, `# generado`, `# solo_verificados` y
`# contenido_sha256` (hash del contenido, §4; filas ordenadas por lat, lng, nombre, id). Columnas:

| Columna | Regla |
|---|---|
| `id_origen` | Informativo (el id en la instalación que exportó). No se usa para cruzar. |
| `nombre` | Obligatoria, 2 a 200 caracteres. |
| `direccion` | Opcional, hasta 300. |
| `lat`, `lng` | Obligatorias, grados decimales (WGS84), `-90..90` y `-180..180`. |
| `fuente` | `manual`, `osm` o `sepa`: cómo nació el local. Vacío = `manual`. |
| `verificado` | `1` o `0`: si un admin ya lo validó. Por defecto solo se exportan los `1`. |
| `referencias` | Vínculos con las fuentes de los ETL, separados por `\|`: `osm:node/123`, `sepa:<comercio>-<bandera>-<sucursal>`. |
| `medios_pago`, `recargo_tarjeta` | JSON (objetos). |

**Qué no lleva:** personas (`creado_por`, usuarios), precios, ni el dato crudo de cada fuente
(`local_fuentes.datos`). Se conservan `fuente` y `referencias` a propósito: los locales de OSM tienen
licencia ODbL y hay que poder separarlos del resto.

**Cómo se importa (por cada fila válida):**

1. **¿Ya existe?** Primero por vínculo (alguna de sus `referencias` ya está vinculada a un local de
   acá). Si no, por la misma regla anti-duplicados del alta de locales: nombre parecido (similitud ≥
   `local_duplicado_similitud`) a menos de `local_duplicado_metros`.
2. **Si existe:** no se pisan sus datos (el admin de acá pudo corregirlos). Solo se le suman los
   vínculos que falten y, si el archivo lo trae verificado y acá no lo estaba, se lo **verifica**
   (esa validación es justo lo que viaja).
3. **Si no existe:** se crea con los datos del archivo, el mismo `fuente` y `verificado`, **sin dueño**
   (`creado_por` nulo: las personas de otra instalación no existen acá) y con sus vínculos.
4. **Idempotente:** importar dos veces el mismo archivo no cambia nada la segunda. El simulacro
   corre la misma lógica dentro de una transacción que se revierte.

Filas inválidas (no frenan el resto, se informan con línea y motivo): `nombre_corto`,
`coordenadas_invalidas`, `coordenadas_fuera_de_rango`, `fuente_invalida`, `verificado_invalido`,
`referencia_invalida`, `json_invalido`.
