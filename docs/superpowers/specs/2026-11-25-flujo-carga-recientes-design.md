# Corte 20: flujo de carga y «Recientes» (diseño corto)

Fecha: 2026-11-25. Estado: **pendiente de aprobación del dueño**. Cierra el release 0.1.x
(`docs/10-roadmap.md`). Toca sobre todo `app/`; el backend solo sube un tope.

## Intención y por qué
Hoy, al guardar un precio, la app muestra «¡Precio cargado!» y «Listo» salta a la pantalla principal
(`popUntil(isFirst)` en `price_screen.dart`). Se pierde el contexto del producto que se acaba de
cargar. Además, en el uso real (mirar antes de ir al súper, y escanear más cosas ya en el local)
conviene que lo recién consultado quede a mano, sin pantallas extra.

## Metas
1. Tras guardar un precio, **volver a la ficha del producto** con un aviso («Precio cargado · karma N»),
   sin pantalla de éxito intermedia. La ficha ya recarga lista, mapa e historial al volver.
2. **«Escanear otro»** en la ficha, para no perder velocidad cuando se escanean varios productos
   seguidos.
3. **«Recientes»**: las últimas 3 o 4 consultas bajo el campo de EAN manual, con **qué es, dónde y a
   cuánto**. Guardadas en el celular (sirven sin red).
4. **Nunca vacío:** si un producto no tiene precio, el botón dice «Sé el primero en cargarlo» y da
   **bonus de karma** por esa primera carga.

## No metas
- Ahorro acumulado, «lo compré acá» o cualquier seguimiento de gastos (principio 1 del roadmap).
- Perfil, listas, seguir productos, notificaciones, «precios por refrescar» (releases 0.2.x en adelante).
- Cambiar el alta de producto: `SugerirScreen` ya vuelve a la ficha.

## Antimetas
Que un precio lejano parezca local. Que «Escanear otro» agregue un toque a quien escanea de a uno.

## Decisiones tomadas
- **Qué precio mostrar en Recientes:** el del local más cercano dentro del radio normal
  (`config.radio_precios_m`, 5 km). Si no hay ninguno, se amplía a un **radio de referencia
  configurable** (`config.radio_referencia_km`, 300 por defecto). Ese precio se muestra **marcado como
  referencia y con su distancia** («a 120 km»), nunca como un precio de la zona.
- **Qué se guarda:** en el celular, por cada consulta, el EAN, el instante y una **foto** (nombre,
  precio, local, distancia y antigüedad vistos). Se actualiza cuando hay red; sin red se muestra la
  foto. Solo en el dispositivo (no se manda al servidor, salvo los eventos del 19b que ya existen).
- **Cuántas:** 3 o 4, las más recientes, sin repetir EAN (reconsultar mueve al tope).
- **Bonus de «Sé el primero»:** karma extra en `config` (`karma_primer_precio`), aplicado cuando el
  producto no tenía ningún precio en ningún local.

## Enfoques considerados
- **A (elegido):** volver con `pop` a la ficha y aviso, sin pantalla de éxito, más «Escanear otro» en
  la ficha. Mínimo cambio, aprovecha la recarga que ya existe.
- **B:** dejar la pantalla de éxito y que «Listo» vuelva a la ficha. Agrega un toque inútil.
- **C:** seguir volviendo a Inicio y mostrar el resultado en Recientes. Pierde el contexto de la ficha.
Elegido A por el dueño («lo mejor de los dos mundos»).

## Constraints
- Android, sin cambiar el `applicationId`. El cliente solo habla con el backend.
- Sin red no debe fallar ni demorar nada nuevo (como la cola de eventos del 19b).
- `precios/vigentes` acepta hoy hasta 100 km (`radio_m` `le=100_000` en `productos.py`): hay que subir
  el tope para el radio de referencia, que se valida contra `config`.

## Para quien construya
- Navegación (`price_screen.dart`, `product_screen.dart`, `home_screen.dart`), almacenamiento local
  de Recientes, endpoint/tope de radio y `config`, bonus de karma en el backend con su regla y tests.
- Tests: Flutter (navegación, Recientes, offline) y backend contra Postgres real (tope de radio,
  bonus una sola vez). Docs al día (Doc 2, `docs/04` si corresponde).
- Decide quien construya, sin preguntar: textos exactos, cómo mostrar «referencia» y el formato de la
  foto guardada.
