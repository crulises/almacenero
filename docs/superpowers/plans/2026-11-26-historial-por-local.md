# Historial de precios por local (corte 22) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un botón en la ficha abre una pantalla con el historial de un producto en un local (el más cercano por defecto, cambiable), con tabs Mapa/Gráfico, variación entre precios y «Escanear otro».

**Architecture:** Backend suma un endpoint (`/productos/{ean}/locales`) que devuelve los locales verificados cercanos con su último precio. La app suma una pantalla nueva que combina ese endpoint con el historial existente filtrado por `local_id`; el gráfico es un `CustomPainter` propio. La lógica pura (variación, rango del eje) va en `domain/` para testearla sin widgets.

**Tech Stack:** FastAPI + asyncpg + pytest (Postgres real), Flutter (`material_ui`, `flutter_map` ya presente), sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-11-26-historial-por-local-design.md`

## Global Constraints

- Comentarios, textos de UI y docs en español rioplatense. Sin dependencias nuevas.
- Backend: solo locales **verificados** y dentro de `config.radio_precios_m`; sin `lat/lng`, solo los que tienen precio de ese producto, el más reciente primero. Se listan con o sin precio cuando hay ubicación.
- Escala del gráfico **lineal**, sin truncar de forma engañosa.
- Frescura y distancia siempre visibles; nunca una pantalla vacía sin explicación.
- Textos fijos: botón de la ficha «Ver historial por local»; sin precios: «Este local no tiene precios de este producto»; botones «Ir al inicio» (secundario, blanco) y debajo «Escanear» (`FilledButton`, color principal); tabs «Mapa» (izq.) y «Gráfico» (der., abre acá); carteles del mapa «Vos» y «Local».
- Tabs del mismo alto que el mapa de la ficha (240).
- Tests: backend contra Postgres real; Flutter unit + widget. `make lint` y `make test` verdes antes del PR. No mergear.

## Review Focus

- Un solo precio en el local: sin variación, el gráfico dibuja un punto (no revienta).
- Todos los precios iguales (rango del eje = 0): el eje no divide por cero y se ve una línea plana.
- Precio igual al anterior: «sin cambios», no «subió 0%».
- GPS denegado o falla: la pantalla igual muestra locales con precio, sin distancia ni «Vos».
- Falla de red al cargar locales o historial: mensaje con «Reintentar», no pantalla en blanco.
- Dos precios en el mismo instante o fechas desordenadas: la variación se calcula sobre orden cronológico.

---

### Task 1: Endpoint `GET /v1/productos/{ean}/locales`

**Files:**
- Modify: `backend/app/api/v1/productos.py`
- Test: `backend/tests/test_productos_locales.py` (nuevo; copiar los helpers `_local`/`_precio`/`admin` de `tests/test_vigentes.py`, con prefijo de nombre `ploc-` y su limpieza)

**Interfaces:**
- Produces: `GET /v1/productos/{ean}/locales?lat=&lng=` → `list[LocalDelProductoOut]` con campos `local_id: UUID, local_nombre: str, lat: float, lng: float, distancia_m: float | None, ultimo_precio: Decimal | None, fecha: datetime | None`. Con `lat` y `lng` (van juntos, si no 422): verificados dentro de `config.radio_precios_m`, **tengan o no precio**, orden por `distancia_m`. Sin ellos: verificados con precio, orden por `fecha` desc, `distancia_m` nulo. `ultimo_precio`/`fecha` son el precio más nuevo del producto en ese local (nulos si no hay).

- [ ] **Step 1: Escribir los tests** (nombres y aserciones):
  - `test_con_ubicacion_lista_locales_cercanos_con_y_sin_precio_ordenados_por_distancia`: dos locales verificados a ~100 m y ~1 km del punto; el cercano sin precio, el otro con precio → ambos aparecen, cercano primero, `ultimo_precio is None` en el primero, `"150.00"` en el segundo, `distancia_m` numérico.
  - `test_excluye_locales_sin_verificar` (`update locales set verificado=false` vía `sql`).
  - `test_excluye_locales_fuera_del_radio` (usar `config_temporal("radio_precios_m", "500")` y un local a 2 km).
  - `test_sin_ubicacion_solo_locales_con_precio_el_mas_reciente_primero`: `distancia_m is None`; el local sin precio no está.
  - `test_ultimo_precio_es_el_mas_nuevo_del_local` (dos cargas, la vieja envejecida con `dias=10`).
  - `test_lat_sin_lng_da_422`.
- [ ] **Step 2: Correr y ver fallar:** `cd backend && pytest tests/test_productos_locales.py -v` → FAIL (404 en la ruta).
- [ ] **Step 3: Implementar** `LocalDelProductoOut` y `locales_del_producto(ean, lat, lng, ...)` en `productos.py`, junto a `precios_vigentes` y con el mismo estilo: `config.leer(pool, "radio_precios_m")`, una sola query con `left join lateral` del último precio por local (`order by fecha desc limit 1`), `where l.verificado` y `st_dwithin` solo si hay ubicación. Registrar la ruta **antes** de cualquier ruta con conflicto de path (no hay; igual verificar que `/productos/{ean}/locales` no choque con `/productos/{ean}`).
- [ ] **Step 4: Correr:** `pytest tests/test_productos_locales.py -v` → PASS; luego `make test` completo del backend sin romper nada.
- [ ] **Step 5: Commit** — `feat(api): GET /productos/{ean}/locales (locales verificados cercanos con su último precio)`.

---

### Task 2: Datos de la app (modelos, repositorio, deps)

**Files:**
- Modify: `app/lib/data/price_repository.dart`, `app/lib/app_deps.dart`, `app/lib/main.dart`
- Modify (fakes que construyen `AppDeps`): `app/test/widget_test.dart` (helper de deps y `PrecioHistorial(...)` en :237, :899, :1318, :1567), `app/test/eventos_test.dart:44`, `app/test/invitacion_integracion_test.dart:85`, y cualquier otro que `flutter analyze` marque
- Test: `app/test/price_repository_test.dart` (nuevo; mirar cómo otros tests de repositorio simulan `AuthedApi`, p. ej. `recientes_test.dart`)

**Interfaces:**
- Produces:
  - `PrecioHistorial` suma `final String localId` (requerido, de `json['local_id']`); los constructores de tests pasan `localId`.
  - `class LocalDelProducto { String localId; String localNombre; double lat; double lng; double? distanciaM; String? ultimoPrecio; DateTime? fecha; bool get tienePrecios => ultimoPrecio != null; factory fromJson }`.
  - `PriceRepository.localesDelProducto(String ean, {Ubicacion? ubicacion}) -> Future<List<LocalDelProducto>>` (GET `/productos/$ean/locales` con `?lat=&lng=` si hay ubicación) y `PriceRepository.historialDeLocal(String ean, String localId) -> Future<List<PrecioHistorial>>` (GET `/productos/$ean/precios?local_id=$localId`).
  - `AppDeps.loadLocalesDelProducto: Future<List<LocalDelProducto>> Function(String ean, {Ubicacion? ubicacion})` y `AppDeps.loadHistorialLocal: Future<List<PrecioHistorial>> Function(String ean, String localId)`, requeridos en el constructor y cableados en `main.dart` a `precios.localesDelProducto` / `precios.historialDeLocal`.

- [ ] **Step 1: Test** `price_repository_test.dart`: `PrecioHistorial.fromJson` lee `local_id`; `LocalDelProducto.fromJson` con precio (`tienePrecios` true) y con `ultimo_precio: null` (false, `distanciaM` nulo si falta); `localesDelProducto` arma la URL con y sin ubicación; `historialDeLocal` agrega `local_id`.
- [ ] **Step 2: Correr** `cd app && flutter test test/price_repository_test.dart` → FAIL.
- [ ] **Step 3: Implementar** lo de Interfaces; actualizar `main.dart` y todos los fakes de `AppDeps`/`PrecioHistorial` hasta que `flutter analyze` no marque nada.
- [ ] **Step 4: Correr** `flutter analyze && flutter test` → todo PASS (la suite existente sigue verde).
- [ ] **Step 5: Commit** — `feat(app): modelos y repositorio de historial por local`.

---

### Task 3: Lógica pura del historial

**Files:**
- Create: `app/lib/domain/historial.dart`
- Test: `app/test/historial_test.dart`

**Interfaces:**
- Consumes: `PrecioHistorial` (Task 2), `formatearPrecio` no hace falta.
- Produces:
  - `class PuntoHistorial { final PrecioHistorial precio; final double? variacionPct; }` y `List<PuntoHistorial> conVariacion(List<PrecioHistorial> masNuevoPrimero)`: devuelve el **mismo orden** (más nuevo primero); `variacionPct` es `(actual − anterior) / anterior × 100` contra el precio cronológicamente anterior, `null` para el más viejo. Ordena internamente por `fecha` (desempate por el orden recibido) para no depender de que llegue ordenado.
  - `String etiquetaVariacion(double? pct)`: `null` → `''`; `|pct| < 0.5` → `'sin cambios'`; positivo → `'subió 8%'`; negativo → `'bajó 12%'` (redondeo a entero, sin signo).
  - `class RangoEje { final double min, max; }` y `RangoEje rangoEje(List<double> valores)`: lineal: `min`/`max` reales de los valores, ampliados con un margen de 10 % del rango a cada lado; si el rango es 0 (todos iguales, o uno solo) devuelve `valor ± 10 %` del valor (nunca divide por cero).

- [ ] **Step 1: Tests** con valores concretos: `conVariacion` con 100→110→99 da `[null, +10, -10]` en cronológico (y la lista devuelta más nuevo primero); un solo precio → `variacionPct` nulo; mismo precio dos veces → `0`; entrada desordenada da lo mismo que ordenada; `etiquetaVariacion(8.4)=='subió 8%'`, `(-12.2)=='bajó 12%'`, `(0.2)=='sin cambios'`, `(null)==''`; `rangoEje([100,100,100])` con `min<100<max`; `rangoEje([100,200])` con `min==90`, `max==210`.
- [ ] **Step 2: Correr** `flutter test test/historial_test.dart` → FAIL.
- [ ] **Step 3: Implementar** en `domain/historial.dart`.
- [ ] **Step 4: Correr** → PASS.
- [ ] **Step 5: Commit** — `feat(app): variación y rango del eje del historial`.

---

### Task 4: Gráfico de líneas

**Files:**
- Create: `app/lib/ui/grafico_precios.dart`
- Test: `app/test/grafico_precios_test.dart`

**Interfaces:**
- Consumes: `PrecioHistorial`, `rangoEje` (Task 3), `formatearPrecioCorto` de `precio.dart`.
- Produces: `class GraficoPrecios extends StatelessWidget` con `GraficoPrecios({super.key, required List<PrecioHistorial> precios, List<MarcaGrafico> marcas = const []})` y `class MarcaGrafico { final DateTime fecha; final String texto; }` (queda previsto para el corte 23; en este corte siempre vacío). Alto lo da el padre. Dibuja con `CustomPaint`: eje Y lineal con rótulos del mínimo y máximo (`formatearPrecioCorto`), eje X con la fecha más vieja y la más nueva (`dd/mm`), línea + un círculo por precio, el último resaltado. Un solo precio → un punto centrado. Con `Semantics` con un resumen leíble («Precio en el tiempo: de $ X a $ Y»).

- [ ] **Step 1: Tests de widget:** pumpear con 3 precios, con 1 precio y con 3 iguales sin excepciones (`tester.takeException()` nulo); `find.byType(CustomPaint)` presente; aparece el texto del precio máximo y mínimo formateados (`$ 1.100`, `$ 900`) y las fechas extremas.
- [ ] **Step 2: Correr** → FAIL.
- [ ] **Step 3: Implementar** `GraficoPrecios` y su `CustomPainter` (`shouldRepaint` por igualdad de datos). Colores del `Theme` (`colorScheme.primary`), nada de colores fijos nuevos: la paleta se cambia en otra sesión.
- [ ] **Step 4: Correr** → PASS.
- [ ] **Step 5: Commit** — `feat(app): gráfico lineal de precios`.

---

### Task 5: Mapa del local con «Vos» y «Local»

**Files:**
- Create: `app/lib/ui/mapa_local.dart`
- Test: `app/test/mapa_local_test.dart`

**Interfaces:**
- Consumes: `Ubicacion` (`data/location_service.dart`), `LocalDelProducto` (Task 2).
- Produces: `class MapaLocal extends StatelessWidget` con `MapaLocal({super.key, required double localLat, required double localLng, Ubicacion? usuario})`. Basado en `flutter_map` igual que `MapaPrecios` (mismas tiles y `userAgentPackageName`, atribución OSM, esquinas redondeadas, sin rotación). Marcador «Local» en el local y, si `usuario != null`, marcador «Vos»; el encuadre incluye ambos (`CameraFit.coordinates`, `maxZoom: 16`; si hay uno solo, centrado a zoom 16).

- [ ] **Step 1: Tests de widget** (mirar cómo `widget_test.dart` maneja `MapaPrecios` con tiles en test): con `usuario` aparecen `find.text('Vos')` y `find.text('Local')`; sin `usuario` solo `'Local'`.
- [ ] **Step 2: Correr** → FAIL.
- [ ] **Step 3: Implementar** con dos `Marker` cuyos hijos son carteles de texto (estilo de `_Cartel` de `mapa_precios.dart`).
- [ ] **Step 4: Correr** → PASS.
- [ ] **Step 5: Commit** — `feat(app): mapa del local con «Vos» y «Local»`.

---

### Task 6: Pantalla `HistorialLocalScreen`

**Files:**
- Create: `app/lib/ui/historial_local_screen.dart`
- Modify: `app/lib/ui/product_screen.dart` (solo extraer «Escanear otro»; ver Task 7)
- Test: `app/test/historial_local_screen_test.dart`

**Interfaces:**
- Consumes: `AppDeps.loadLocalesDelProducto`, `loadHistorialLocal`, `obtenerUbicacion`, `pantallaEscaneo` (Tasks 2), `conVariacion`/`etiquetaVariacion` (3), `GraficoPrecios` (4), `MapaLocal` (5), `formatearPrecio`, `formatearFecha`, `formatearDistancia`.
- Produces: `HistorialLocalScreen({super.key, required Producto producto, required AppDeps deps})` y la función compartida `Future<void> escanearOtro(BuildContext context, AppDeps deps)` en un archivo nuevo `app/lib/ui/escanear_otro.dart` con el comportamiento actual de `_escanearOtro` de la ficha (push de `pantallaEscaneo`, `pushReplacement` a `ProductScreen(via: 'camara')`; cancelar no hace nada).

Comportamiento:
- AppBar: título = nombre del local elegido (con distancia al lado si hay: `formatearDistancia`), tocable (icono ▾) → abre selector (`showModalBottomSheet`) con los locales en el orden recibido, cada uno con nombre, distancia, y «sin precios» si `!tienePrecios`. Acción: `TextButton.icon` «Escanear otro» (mismo icono/label que la ficha, llama `escanearOtro`).
- Bajo el AppBar: nombre del producto (`titleMedium`) y su `detalle`.
- `TabBar` con «Mapa» (primero) y «Gráfico» (segundo, `initialIndex: 1`); el contenido de ambos tabs mide 240 de alto.
- Debajo: lista de precios del local elegido, más nuevo primero: precio, `formatearFecha` con frescura (reutilizar el color/etiqueta de `frescura.dart` si se puede construir sin `PrecioVigente`; si no, un texto «hace N días» alcanza) y `etiquetaVariacion`.
- Carga: `obtenerUbicacion` (si falla → `null`, sin error visible) → `loadLocalesDelProducto(ean, ubicacion:)` → elige el primero → `loadHistorialLocal`. Cambiar de local recarga solo el historial.
- Local sin precios (lista vacía del historial) o ninguna opción en la lista: mensaje «Este local no tiene precios de este producto» y debajo `OutlinedButton` «Ir al inicio» (`Navigator.popUntil(isFirst)`) y `FilledButton` «Escanear» (`escanearOtro`). Si no hay **ningún** local para elegir: «No hay locales cercanos con precios de este producto» con los mismos dos botones.
- Error de red en cualquier carga: texto + `TextButton` «Reintentar».

- [ ] **Step 1: Tests de widget** (con los fakes de `AppDeps` de `widget_test.dart`; si ese helper es privado a ese archivo, extraerlo a `app/test/helpers_deps.dart` en esta task sin cambiar su comportamiento):
  - título con nombre del local más cercano y su distancia; producto bajo el título.
  - abre en el tab «Gráfico» (hay `GraficoPrecios`); tocar «Mapa» muestra «Local».
  - filas con `bajó 12%` / `subió 8%` y un solo precio sin etiqueta de variación.
  - cambiar de local desde el selector pide el historial de ese `localId` y actualiza el título.
  - local sin precios: texto fijo + «Ir al inicio» + «Escanear»; «Ir al inicio» vuelve a la primera ruta.
  - sin ubicación (`obtenerUbicacion` lanza): pantalla carga, sin distancia en el título, mapa sin «Vos».
  - error al cargar locales: «Reintentar» recupera.
  - «Escanear otro» abre el escaneo y reemplaza por la ficha del EAN devuelto.
- [ ] **Step 2: Correr** `flutter test test/historial_local_screen_test.dart` → FAIL.
- [ ] **Step 3: Implementar** `escanear_otro.dart` (extraído de la ficha, que pasa a usarlo) y `HistorialLocalScreen` según lo de arriba. Usar `DefaultTabController` o un `TabController` propio con `initialIndex: 1`.
- [ ] **Step 4: Correr** `flutter analyze && flutter test` → PASS completo.
- [ ] **Step 5: Commit** — `feat(app): pantalla de historial por local`.

---

### Task 7: Botón en la ficha y fin de la sección vieja

**Files:**
- Modify: `app/lib/ui/product_screen.dart`, `app/test/widget_test.dart` (tests de la sección «Historial de precios», ~:899-909, y los que dependan de `_historial` de la ficha)
- Test: `app/test/widget_test.dart` (grupo de la ficha)

**Interfaces:**
- Consumes: `HistorialLocalScreen` (Task 6), `escanearOtro` (Task 6).
- Produces: en `_ficha`, un `OutlinedButton.icon` «Ver historial por local» (icono `Icons.show_chart`) **encima** de «Cargar precio»; ambos ocupan el ancho y van en columna bajo el nombre del producto (el layout `Row` actual deja de caber). La sección «Historial de precios» y `_historialPrecios` se eliminan de `_cuerpoPrecios`. `_historial` se **conserva** solo para decidir «Sé el primero en cargarlo» (y `_recargarPrecios` lo sigue refrescando). El botón nuevo se oculta si `primero` (nadie cargó nada: no hay historial que ver).

- [ ] **Step 1: Tests:** en la ficha de un producto con precios aparece «Ver historial por local» y queda por encima de «Cargar precio» (`tester.getTopLeft(...).dy`); tocarlo abre `HistorialLocalScreen`; ya no existe el texto «Historial de precios»; con historial vacío no aparece el botón (sigue «Sé el primero en cargarlo»). Ajustar/eliminar el test viejo de la sección «Historial de precios».
- [ ] **Step 2: Correr** → FAIL.
- [ ] **Step 3: Implementar** los cambios de Interfaces en `product_screen.dart`.
- [ ] **Step 4: Correr** `make lint && make test` → PASS.
- [ ] **Step 5: Commit** — `feat(app): botón «Ver historial por local» en la ficha`.

---

### Task 8: Documentación y PR

**Files:**
- Modify: `docs/01-producto-vision.md` (comportamiento de la pantalla y de la ficha), `docs/02-spec-tecnico.md` (endpoint `/productos/{ean}/locales`, pantalla, el gráfico propio), `docs/04-plan-v0.2.md` (cortes 22 y 23 en la tabla de alcance y una sección «Corte 22» con qué se prueba en el celular), `docs/10-roadmap.md` (anotar «configuración por secciones» y «categorías/rubros editables, muchos a muchos» como proyectos pendientes), `CLAUDE.md` si algo del alcance lo pide
- Modify: el diseño (`docs/superpowers/specs/2026-11-26-historial-por-local-design.md`): estado «aprobado» + lo que cambió al implementar

- [ ] **Step 1:** Actualizar los docs de arriba (seguir el estilo de los cortes 20 y 21 ya escritos).
- [ ] **Step 2:** `make lint && make test` completos y verdes (pegar el resumen en el PR).
- [ ] **Step 3:** `git push -u origin feat/historial-por-local` y abrir el PR a `main` con «Qué probar en el celular» (entrar a un producto con precios en un local cercano; gráfico y mapa con «Vos»/«Local»; cambiar de local; local sin precios y sus botones; «Escanear otro»; GPS apagado) y la nota de que **no se mergea sin el OK del dueño**. Seguir las reglas del repo para bind del PR.
