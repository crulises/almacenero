# Historial de precios por local (cortes 22 y 23) — diseño

Fecha: 2026-11-26. Estado: **aprobado por el dueño; corte 22 implementado, pendiente de probar en el celular**. Release 0.2.x
(`docs/04-plan-v0.2.md`). Es una **primera versión para ver cómo queda**: la UI probablemente cambie
después para mejorar la UX, así que se hace simple y con el estilo actual.

## Intención y por qué
Transparencia de precios. Quien está frente a un descuento tiene que poder ver cómo se movió el
precio **de ese producto en ese local** y juzgar si el descuento es real. Hoy la ficha tiene una sección
«Historial de precios» que mezcla todos los locales en una lista plana, sin variación ni frescura:
no sirve para esto.

## Dos cortes, dos PR (el dueño prueba cada uno en el celular)
- **Corte 22 — Pantalla de historial por local:** botón, selector de local, tabs Mapa/Gráfico, filas con
  variación, gráfico lineal, caso «sin precios». Rama `feat/historial-por-local`.
- **Corte 23 — Hitos:** marcas manuales («Aumento de combustibles 30%») cargadas desde el panel de admin y
  dibujadas como líneas verticales en el gráfico. Rama propia, parte de `main` con el 22 ya mergeado.

## Metas (corte 22)
1. Botón **«Ver historial por local»** en la ficha, **encima** de «Cargar precio», que abre la pantalla.
2. La pantalla es **de un producto en un local**. Título: nombre del local con su distancia; **debajo,
   nombre y detalle del producto** (para saber de qué se habla).
3. Local por defecto: **el más cercano**; si el usuario está parado en un local (dentro del geofence),
   ese. Se puede cambiar desde un selector, ordenado por distancia.
4. «Escanear otro» arriba a la derecha, con el mismo comportamiento que en la ficha.
5. Dos tabs bajo el nombre: **Mapa** (izquierda) y **Gráfico** (derecha, la principal: abre en ella).
   Ambos del mismo tamaño (el del mapa de la ficha).
6. **Gráfico:** línea del precio en el tiempo, **escala lineal** (sin truncar el eje a conveniencia: debe
   leerse lo que pasó de verdad).
7. **Mapa:** muestra el local y la posición del usuario, con carteles **«Vos»** y **«Local»**.
8. **Lista de precios** del local (debajo de los tabs): precio, fecha con frescura y **variación contra
   el precio anterior en ese local** («subió 8%», «bajó 12%»).
9. **Sin precios en el local:** mensaje simple («Este local no tiene precios de este producto»), con dos
   botones: «Ir al inicio» (blanco/secundario) y debajo «Escanear» (color principal).

## No metas
- Ahorro acumulado, «lo compré acá» ni nada de tracker financiero (principio 1 del roadmap).
- Rediseñar la paleta o la marca (otra sesión del dueño; se usa el tema actual, que queda en un lugar).
- Reorganizar la configuración al estilo GitHub/fly.io: **proyecto aparte**, anotado en el roadmap.
- Hitos en este corte (van en el 23). El gráfico queda con el lugar previsto (una lista de marcas vacía).

## Antimetas
Que un descuento falso parezca real por un eje recortado. Que un local lejano o sin verificar se confunda
con «el de acá». Mostrar un vacío sin explicación.

## Qué locales se pueden elegir (decisión del dueño)
Solo **locales verificados** (su ubicación es conocida) y **cerca**, según `config.radio_precios_m`. Un
local sin verificar no tiene ubicación confiable, así que no aparece. Se listan **tengan o no precio** de
este producto (por eso existe el mensaje «sin precios»); el selector marca cuáles tienen precios.
**Sin permiso de GPS:** no se puede saber qué está cerca. La pantalla muestra los locales verificados
**que ya tienen precio de este producto**, sin distancia, el de precio más reciente primero, y el mapa sin
«Vos». *(Mi propuesta; el dueño preguntó qué significaba el caso y no lo cerró.)*

## Aproximaciones consideradas
1. **Reutilizar `/locales/cerca` + `/precios?local_id=` + `/precios/vigentes` en el cliente.** Sin backend
   nuevo, pero `/locales/cerca` tiene tope de 5 km fijo y límite de 20, incluye sin verificar, y no usa
   `radio_precios_m`; habría que armar la lista cruzando tres respuestas en la app.
2. **Un endpoint nuevo `GET /v1/productos/{ean}/locales`** (elegida): devuelve los locales verificados
   dentro de `radio_precios_m` con `distancia_m` y `ultimo_precio`/`fecha` (nulos si no hay), ordenados por
   distancia; sin `lat/lng`, solo los que tienen precio. Un viaje, reglas en el backend, testeable contra
   Postgres.
3. **Pantalla sobre la ficha actual (reemplazar el historial en línea).** Descartada: el dueño lo
   quiere como pantalla aparte.

## Cambios técnicos (corte 22)
- **Backend:** el endpoint nuevo de (2). `PrecioOut` ya trae `local_id`: no cambia. Tests de pytest
  contra Postgres real (verificado/no, radio, sin precio, sin ubicación).
- **App:** `PrecioHistorial` suma `localId`; modelo y repositorio para el endpoint nuevo; pantalla
  `historial_local_screen.dart`; `CustomPainter` para el gráfico (**sin librería nueva**, a elección mía:
  una línea, eje lineal y marcas verticales son poco código); `escanear otro` se comparte con la ficha
  (se extrae). Frescura y distancia con los helpers existentes (`frescura.dart`, `formatearDistancia`).
- **Sección «Historial de precios» de la ficha:** **se reemplaza por el botón** (decisión mía: recomendada
  y el dueño no objetó); el historial mezclado desaparece de la ficha.
- **Docs:** Doc 1 (comportamiento), Doc 2 (endpoint, pantalla), `docs/04-plan-v0.2.md` (cortes 22 y 23),
  `docs/10-roadmap.md` (config por secciones queda anotada), `CLAUDE.md` si hace falta.

## Corte 23 — Hitos (esbozo; se detalla al terminar el 22)
- Tabla `hitos` (fecha, texto, `categorias` nulo = todas), CRUD en el panel de admin, lectura para la app.
- Globales por defecto; la ficha del hito permite acotarlos a rubros/categorías. **Hoy el catálogo no tiene
  categoría por producto**, así que el filtro se guarda pero no aplica hasta que exista esa clasificación.
- Las categorías/rubros del catálogo tienen que ser **editables** y un producto puede pertenecer a
  **varias** (relación muchos a muchos). Dejarlo en cuenta al modelar; la clasificación en sí es un
  proyecto aparte, anterior o paralelo al corte 23.
- Varios hitos el mismo día y misma categoría: **la app toma uno al azar** y lo marca; se pule luego.
- Pregunta para entonces: cómo se ve el hito en el gráfico (línea + texto al tocar).

## Qué se prueba en el celular (corte 22)
Entrar a un producto con precios en un local cercano, ver gráfico y mapa («Vos» y «Local»), cambiar de
local, un local sin precios (mensaje y botones), «Escanear otro», y con GPS apagado.

## Lo que queda a criterio del implementador
Formato de la variación (porcentaje redondeado), qué pasa con un solo precio (sin variación, un punto),
cómo se rotula el eje, y los tamaños exactos.
