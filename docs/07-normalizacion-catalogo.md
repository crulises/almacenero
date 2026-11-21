# Doc 7 — Calidad y normalización del catálogo

**Estado: borrador de diseño (fase 1), sin implementar.** Las mediciones son del
2026-11-21 sobre la base local (134 505 productos: SEPA de un día + OFF de Argentina y
vecinos; ver Doc 5 §2b). No es fuente de verdad del producto (Doc 1) ni de la
arquitectura (Doc 2). El plan de cortes está en `docs/04-plan-v0.0.2.md` §10.

> Nombre real de la tabla de datos crudos: `producto_fuentes` (no «productos_fuente»).

## 1. Qué medimos (defectos reales, sobre 134 505 productos)

| Defecto | Productos | % | Comentario |
|---|---|---|---|
| Sin tamaño (campo vacío) | 82 130 | 61,1 | SEPA: 50 538 de 78 025 |
| …pero el nombre **trae** un tamaño (`500ml`, `X 30 Grs`, `BOT-750-ml.`) | 15 166 | 11,3 | **extraíble**: un prototipo de regex recuperó 14 041 (SEPA 11 890, OFF 2 151) |
| Marca = placeholder (`S/d`, `sin Marca`, `Generico`) | 16 627 | 12,4 | hay que tratarlos como «sin marca» |
| Sin marca (vacía) | 17 158 | 12,8 | se superpone con lo anterior solo en parte |
| Marca repetida dentro del nombre | 42 867 | 31,9 | tope superior (incluye coincidencias legítimas) |
| Marcas: variantes de escritura | 19 022 → 15 709 | −17 % | `Nestle/NESTLE/Nestlé/NESTLÉ.`: 7 formas de una; `Cuisine & Co`: 12 |
| Marca truncada (es prefijo de otra marca) | 1 535 | — | `Lysof`, `Aceite Canue` |
| Nombre con un token en MAYÚSCULAS dentro de un nombre mixto | 13 561 | 10,1 | `Jugo LOS NARANJOS - Pomelo rosado` |
| Nombre todo en MAYÚSCULAS | 2 543 | 1,9 | (SEPA ya pasa a «Título» solo lo que viene todo en mayúsculas) |
| Nombre todo en minúsculas / empieza en minúscula | 2 867 / 5 793 | 2,1 / 4,3 | |
| Sufijo de envase de SEPA (`CJA-150-gr.`, `BOT-750-ml.`, `CUB-1-un.`) | 5 632 | 4,2 | `BOT` 1 408, `PAQ` 951, `CJA` 562, `BSA` 544, `FCO` 265… |
| Puntuación final (`.`, `,`) | 9 759 | 7,3 | |
| Pack `X 6 Uni` / `NxM` en el nombre | 1 915 / 3 389 | 1,4 / 2,5 | |
| Nombre de una sola palabra | 7 402 | 5,5 | |
| Nombre sin escritura latina (coreano, árabe, cirílico…) | 2 974 | 2,2 | casi todo OFF de Chile/Brasil |
| Nombre solo dígitos / símbolos | 104 | 0,08 | |
| Nombre con fecha / hora / `VENC` | 107 | 0,08 | |
| Nombre que empieza con un código numérico largo | 102 | 0,08 | |
| Nombres duplicados (mismo nombre, marca y tamaño; distinto EAN) | 4 476 grupos | — | pueden ser variantes legítimas |
| Sin imagen | 92 259 | 68,6 | SEPA no trae imágenes (74 024 de 78 025) |

Hallazgos que cambian el diseño:

1. **El mayor defecto no es el estilo, es el tamaño.** SEPA manda `cantidad = 1` y
   `unidad = UNI/EA/unidad` en ~45 000 filas (la presentación es «una unidad», no el
   contenido): ahí el tamaño real está **en el nombre**. Es la ganancia más grande y es
   determinista.
2. **El campo de SEPA a veces miente.** `cantidad = .25`, `unidad = gr.` con el nombre
   diciendo `250g` (1 374 filas con `gr.`/`ml.` sin tamaño usable). Ante un campo
   imposible, el nombre manda y el producto queda marcado «revisar».
3. **Descartar por incompletitud sacaría demasiado.** «Nombre usable pero sin marca ni
   tamaño real» es el 22,2 % (29 895). Nombre inservible: solo **266** (0,2 %), de los
   cuales 152 no tienen nada más. El umbral de descarte duro tiene que ser el segundo, no
   el primero.
4. **La marca de SEPA a veces es el fabricante** (`Agro Aceitunera S.a.`), no la marca
   comercial (`Cebila`). Se detecta por sufijo societario (`S.A.`, `S.R.L.`, `S.A.C.I.`).
5. **Hay productos que no son comestibles** (textil, hogar: `Tex`, `Hg`, `Home` son de
   las palabras más frecuentes). Es una decisión de producto, ver Doc 4 §10.

## 2. Principios

- **Determinista y versionado.** `normalizar(entrada) → salida` es una función pura (sin
  red, sin reloj, sin base). Mismo input, mismo output. Tiene `NORMALIZADOR_VERSION`; si
  cambia una regla, sube la versión y se puede **re-normalizar** desde `producto_fuentes`
  (el dato crudo no se toca nunca) sin volver a bajar nada.
- **No inventa.** Solo quita, reordena, capitaliza y expande lo que está en el diccionario.
  No agrega palabras («Aceite Oliva» no se vuelve «Aceite de Oliva»), no adivina marcas
  por parecido: una marca solo se corrige si está en el lookup.
- **Lo que decide un humano gana.** Los campos bloqueados (trigger existente) no se
  tocan; el normalizador corre dentro de la misma fusión (`etl/comun/catalogo.py`) y
  respeta `campos_bloqueados`.
- **Calidad = estado + puntaje, no todo-o-nada.** Lo muy incompleto o inservible
  se **oculta** (estado `descartado`, §5) y se puede completar; lo dudoso se muestra, con
  estado, y el panel permite revisarlo.
- **Se mide antes y después.** `make catalogo-calidad` imprime esta misma tabla sobre la
  base; cada corte tiene que mover los números.

## 3. Salida: la ficha

La ficha (lo que ve quien escanea) tiene **un nombre limpio** arriba y los **detalles
estructurados** abajo:

```
Aceite de Oliva Clásico              ← nombre (sin marca, sin tamaño, sin envase)
Cañuelas · 500 ml · Botella PVC      ← marca · tamaño · presentación
EAN 7792180000057 · fuente SEPA
```

Columnas nuevas en `productos_canonicos` (migración en el corte de integración):

| Columna | Qué es |
|---|---|
| `nombre` (existente) | el nombre **normalizado de visualización** |
| `marca` (existente) | marca **canónica** (del lookup), o null si era placeholder/desconocida |
| `tamano_valor`/`tamano_unidad` (existentes) | **contenido total** (para el precio por kg/l) |
| `pack_cantidad` int null | unidades del pack (`24` en «24x275ml»); el tamaño sigue siendo el total (6,6 l) |
| `presentacion` text null | envase en minúscula del diccionario: `botella`, `caja`, `doypack`, `lata`… |
| `calidad` smallint | 0–100 |
| `estado_calidad` text | `completo`, `parcial`, `dudoso`, `descartado` (check) |
| `calidad_motivos` text[] | por qué: `sin_marca`, `sin_tamano`, `nombre_corto`, `no_latino`, `tamano_en_conflicto`… |
| `normalizador_version` int | con qué reglas se calculó |

El nombre **original** de cada fuente queda en `producto_fuentes.datos` (ya está). El
panel lo muestra al lado (ya lo hace la ficha de producto: «qué dijo cada fuente»).

**Quitar la marca del nombre:** solo si la marca es confiable (está en el lookup o la
fuente la trae y aparece entera como secuencia de palabras en el nombre). Si no, el nombre
se deja y se marca `marca_en_nombre`. **Quitar el tamaño del nombre:** solo si el tamaño
extraído coincide con el campo (o el campo estaba vacío); si discrepan, no se toca el
nombre y queda `tamano_en_conflicto`.

## 4. Reglas del normalizador (en orden)

1. **Limpieza de texto:** NFC, quitar NUL y caracteres de control, colapsar espacios,
   recortar puntuación final suelta (`.`, `,`, `-`).
2. **Sufijo de envase de SEPA** `^(.*)\s([A-Z]{2,4})-(\d+(?:\.\d+)?)-(gr|ml|un|lt|kg|cc)\.?$`:
   `BOT-750-ml.` → presentación `botella` + tamaño 750 ml. El código se mapea con un
   diccionario (`BOT`, `PAQ`, `CJA`, `BSA`, `FCO`, `POT`, `DOY`, `PCK`, `LAT`, `PET`,
   `EST`, `BLI`, `SOB`, `AER`, …). `CUB-1-un.` (una unidad) no aporta tamaño.
3. **Códigos internos:** `^0{2,}\d+\s` (código de ERP pegado adelante) se quita; si el
   resultado queda sin letras, el nombre es inservible (§5).
4. **Tamaño y pack del nombre** (después de 2): `500ml`, `X 30 Grs`, `x100Gr`, `2.25 lt`,
   `24x275ml`, `X 6 Uni`. Se reutiliza `etl/comun/tamano.py` (ya multiplica packs). `1 u`
   no es un tamaño. Si hay varios candidatos distintos, no se extrae y queda
   `tamano_ambiguo`.
5. **Reconciliar con el campo de la fuente:** si el campo existe y coincide (1 %,
   `tamanos_equivalentes`), se queda; si el campo es «1 UNI/EA» (no informativo) y el nombre
   trae tamaño, gana el nombre; si discrepan de verdad (otro orden de magnitud, o `.25 gr.`
   vs `250g`), gana el nombre **si el campo es físicamente inverosímil** (< 1 g, < 1 ml) y,
   si no, se conserva el campo y queda `tamano_en_conflicto`.
6. **Marca:** (a) placeholder (`S/d`, `sin marca`, `generico`, `n/a`, `.`, `-`) → null;
   (b) razón social (`S.A.`, `S.R.L.`…) → no es marca: va a `fabricante` en el dato crudo y
   se busca la marca en el nombre contra el lookup; (c) clave `lower + sin acentos + sin
   signos`; si está en el lookup de alias → marca canónica; si no, se capitaliza como
   título; (d) marca truncada que es prefijo único en el lookup → completarla (solo con
   entrada explícita).
7. **Marca fuera del nombre** (ver §3).
8. **Abreviaturas** (diccionario `etl/comun/datos/abreviaturas.csv`, solo las
   **inequívocas**): `p/` → `para`, `c/` → `con`, `s/` → `sin`, `x` suelto antes de un
   número es «por», `clas` → `clásico`, `s/sal` → `sin sal`. Las **ambiguas** (`desc` =
   descremado/descartable/descuento; `ch` = chocolate/chico) **no** se expanden sin
   contexto: se dejan y reciben `abreviado` si el nombre tiene ≥ 2 tokens abreviados.
9. **Capitalización:** si el nombre es todo MAYÚSCULAS o todo minúsculas → «Título» con
   partículas en minúscula (`de`, `la`, `con`, `para`, `y`, `en`, `del`, `sin`, `al`, `por`)
   y unidades/siglas fijas (`ml`, `kg`, `cc`, `uht`, `pet`, `tacc`, `sa`). Si es mixto, se
   respeta lo que escribió quien cargó, **salvo** los tokens en MAYÚSCULAS de ≥ 4 letras
   que no estén en la lista de siglas (que se pasan a Título): `Jugo LOS NARANJOS` →
   `Jugo Los Naranjos`.
10. **Puntaje y estado** (§6).

Idiomas y escrituras: ver §7.

## 5. Qué se muestra y qué no (decidido con el dueño)

Los registros **muy incompletos o inservibles no se muestran**: reciben `estado_calidad =
'descartado'`. Se guardan igual en `productos_canonicos` (con su crudo en `producto_fuentes`),
para no perderlos y para que el panel los liste; pero la búsqueda por EAN de la app los trata
como **«no encontrado»**. Cuando una persona autorizada los completa, se recalcula el estado y
pasan a verse (§5.1).

| Situación | Estado |
|---|---|
| Nombre sin ninguna letra, con fecha/hora de vencimiento, o de < 2 caracteres útiles | `descartado` (`nombre_inservible`) — 266 productos (0,2 %) |
| Nombre usable **sin marca real, sin tamaño y de ≤ 2 palabras** (ej. `Aceite`) | `descartado` (`muy_incompleto`) — ≈ 5 100 productos (3,8 %, medido) |
| Todo lo demás | `completo` / `parcial` / `dudoso` (§6) |

Total descartado hoy: ≈ 5 400 (4,0 %). Es **reversible**: el umbral es una constante
versionada con el normalizador; cambiarlo y correr `make catalogo-renormalizar` los
reclasifica sin tocar las fuentes.

### 5.1 Completar lo que falta: alta e edición simple

Lo descartado y lo dudoso se arreglan con una **interfaz simple para admins y moderadores**
(dos pasos: «buscar por EAN» → formulario corto):

- Campos: nombre, marca (con autocompletado del lookup), tamaño + unidad, presentación.
  Nada más. Se ve al lado lo que dijo cada fuente (crudo) para copiar.
- Si el EAN **no existe** en ningún lado (producto nuevo), es un **alta**; si existe
  (descartado/dudoso), es una **corrección**. En el panel (admin) se aplica directo y queda
  bloqueado contra el ETL; en la app (moderador) va a la **cola de sugerencias** (Doc 4 §10-D)
  y un admin la aprueba.
- Una carga manual nunca se descarta: si pasa por acá, el estado se calcula normal y el
  origen es `manual`.

## 6. Puntaje y estados

Puntaje 0–100 (todo configurable por constantes versionadas con el normalizador):

| Criterio | Puntos |
|---|---|
| Nombre usable (latino, ≥ 1 palabra, sin fecha) | base 40 |
| Nombre de ≥ 2 palabras | +10 |
| Marca canónica (lookup o fuente confiable) | +20 |
| Tamaño válido | +20 |
| Imagen | +5 |
| Presentación | +5 |
| Penalizaciones | `tamano_en_conflicto` −20, `abreviado` −10, `marca_en_nombre` −5 |

`estado_calidad`: **completo** (≥ 75), **parcial** (40–74), **dudoso** (< 40 o con
`tamano_en_conflicto`) y **descartado** (§5; se decide antes del puntaje). Con los números de hoy: 36 % tendría marca + tamaño (el máximo
actual); la extracción debería subir ese número a ~47 % solo por tamaño (+11 pp).

El panel filtra y ordena por estado y puntaje y tiene un **tablero de control** (conteo por
estado y por motivo, con enlace al listado filtrado): «dudosos primero», para que lo poco
que vale la pena corregir a mano aparezca arriba. Lo corregido a mano queda bloqueado y su
puntaje se recalcula.

## 7. Idiomas y escrituras no latinas

**Se cargan y se muestran tal cual.** `8801043004398` («시원한 메밀소바», Nongshim, un fideo
real de Corea que aparece en Chile) es **correcto**: el producto existe y el nombre es el
de su fabricante; que no lo lea un rioplatense no lo vuelve un error. Se marca
`no_latino` (estado `parcial`) y la app lo muestra sin transliterar (transliterar sería
inventar). `7801003785580` (solo nombre coreano, sin marca ni tamaño) es el mismo caso con
menos datos: `parcial`, a la espera de una sugerencia (§4, cola de sugerencias del Doc 4
§10) o de que OFF lo complete.

## 8. Los casos reales, uno por uno

| Caso | Hoy | Con el normalizador |
|---|---|---|
| `Aceite Cebila Oliva pet 3000 cc` (SEPA; marca `Agro Aceitunera S.a.`) | tamaño 3 l (de SEPA), marca = razón social | razón social → fabricante; marca `Cebila` (alias), nombre `Aceite Oliva`, tamaño 3 l, presentación `PET`. Estado `completo`. |
| `Aceite Chef Oliva Extra Virgen` | sin tamaño | no hay de dónde sacarlo: queda `parcial` (`sin_tamano`). **No se inventa.** |
| `ACEITE CANUELAS OLIVA CLAS.PVC 500ml.` (marca `Aceite Canue`) | nombre mixto; tamaño 500 ml; marca truncada | marca `Cañuelas` (por alias `aceite canue`); nombre `Aceite Oliva Clásico`; tamaño 500 ml; presentación `PVC`. |
| Mayúsculas mezcladas con capitalizadas | 13 561 con un token en mayúsculas | regla 9. |
| Marca repetida en el nombre | 31,9 % (tope) | regla 7, solo con marca confiable. |
| Tamaño en el nombre y no en el campo | 15 166 | reglas 2 y 4: ~14 000 recuperables (medido). |
| Solo `Aceite` (sin marca ni tamaño) | 111 nombres genéricos de este tipo | `descartado` (`muy_incompleto`, §5); se completa con la interfaz simple (§5.1). |
| ¿Cambia el EAN si cambia el tamaño? | — | **Sí, según GS1**: cualquier cambio del contenido neto declarado exige un GTIN nuevo ([regla «declared net content»](https://gs1.org/1/gtinrules/en/rule/266/declared-net-content)); el 20 % es de dimensiones/peso bruto. En la práctica algunos fabricantes lo incumplen, así que el tamaño sigue siendo un dato por EAN que se **concilia** entre fuentes (conflicto de tamaño, ya implementado), no una verdad. |
| `8801043004398` (coreano, completo) | cargado | **correcto** (§7), `parcial` por `no_latino`. |
| `7801003785580` (coreano, solo nombre) | cargado | `parcial`, a completar por sugerencia. |
| `7891121035001` (`0000018353 Gin Com Tonica Seager S 24x275ml`) | todo en el nombre | quita el código, `24x275ml` → pack 24, tamaño total 6,6 l; marca `Seager's` **solo si** está en el lookup (si no, `sin_marca`); ⚠ `Com` es portugués («con»): la fuente es brasileña y el diccionario es solo español, así que el nombre queda `Gin Com Tonica Seager S`. Resultado probable `parcial`. |
| `8052467549754` (nombre `0238321840`) | cargado | `descartado` (§5): no se ve en la app. |
| `7898972607067` (`06:39 VENC:27/12/24`) | cargado | `descartado` (§5). |
| `7790520995285` (Lysoform) | SEPA: `Desinfect Amb Origin`, `Lysof`, 380 ml; OFF: `Lysoform`, sin tamaño | marca → `Lysoform` (alias `lysof`); el nombre queda abreviado (`abreviado`, `dudoso`). **El 380 ml vs 257 g / 360 cm³ del envase no lo resuelve ningún software**: lo corrige una persona (admin, o moderador por sugerencia) y queda bloqueado. OFF no trae tamaño, así que ni siquiera hay conflicto automático. |

## 9. Diccionarios y lookup (archivos del repo, no código)

- `etl/comun/datos/marcas.csv` — `alias,marca`. Arranca de la **medición**: las 2 000 marcas
  más frecuentes (cubren la mayor parte de los productos) con su forma canónica, que el
  dueño revisa de una pasada. Por qué un archivo y no una tabla: el ETL es determinista y
  reproducible sin base; el archivo se versiona con git y entra en `normalizador_version`.
  Más adelante puede pasar a una tabla editable desde el panel (sin cambiar el normalizador:
  solo la fuente del diccionario).
- `etl/comun/datos/abreviaturas.csv` — `patron,expansion,contexto`.
- `etl/comun/datos/envases.csv` — `codigo,presentacion` (`BOT,botella`).
- **Herramienta de descubrimiento:** `make catalogo-abreviaturas` lista los tokens
  frecuentes que parecen truncados (prefijo de otra palabra más frecuente) para que el
  dueño apruebe o rechace; no aplica nada solo.

## 10. Tests

Fixtures con los casos reales de §8 (entrada cruda → salida exacta), más propiedades:
idempotencia (`normalizar(normalizar(x)) == normalizar(x)`), no agrega palabras que no
estén en la entrada o el diccionario, y no toca campos bloqueados. Es la misma convención
del repo: pytest, sin mocks; la integración con la fusión corre contra Postgres real.
