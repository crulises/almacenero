# Doc 1 — Producto y visión

App de precios compartidos. Documento de producto: qué es, para quién y cómo se
debe comportar. Fuente de verdad para decisiones de comportamiento.

## Problema

Comparar precios de un producto entre locales obliga a recorrerlos uno por uno.
Es lento y se hace en soledad.

## Solución

Un registro colaborativo de precios. Cada usuario carga el precio de un producto
en el local donde está parado. El resto ve esos precios sin tener que ir. Entre
todos mapean el precio de un mismo artículo en varios locales a la vez.

## Usuarios y acceso

- Arranca como grupo cerrado (amigos, ~50 personas).
- Se diseña como si fuera abierto: cualquiera podría crearse usuario.
- Un switch de configuración (admin) define el modo de acceso: abierto / solo
  invitación / alta manual por admin.

## Identidad

- El usuario arranca anónimo, para no poner fricción.
- Luego puede ligar su cuenta a email o social (Google primero; otros más adelante).
- Al ligarse, el usuario anónimo se atribuye a la persona real.
- Cada carga y cada validación quedan atribuidas a un usuario.

## Modelo conceptual

Dos clases de producto, tratadas distinto:

- **Canónico**: tiene código de barras (EAN). Identidad global; mismo EAN = mismo
  producto en todo el país. Se siembra desde Open Food Facts.
- **Genérico / local**: pan casero, miel, productos de balanza. Sin identidad
  global. Se compara por categoría, nunca por identidad. Está atado al local (el
  pan de un local no es el de otro). Se etiqueta como "parecido", no "igual".

Nota de balanza: un EAN que empieza con `2` es interno del local (peso/precio
variable), no global. Se trata como genérico.

Entidades:

- Producto (canónico o genérico).
- Local (negocio físico o emprendimiento).
- Precio: apunta a un producto + un local + una fecha.
- Usuario: con karma / reputación.

El tamaño y la unidad (500 g, 1 L) se guardan siempre, para calcular precio por
kilo/litro y comparar productos de distinto tamaño.

## Reglas de comportamiento

### Frescura del precio

- En Argentina la inflación envejece precios rápido. Ventana inicial: ~1 mes,
  configurable por rubro.
- Siempre se muestra la fecha del precio, bien visible.
- La confianza decae con el tiempo: verde → amarillo → rojo (umbrales configurables).
- Un precio viejo puede mostrarse con una estimación visual ajustada por IPC/REM
  del INDEC, SIEMPRE marcada como estimación y NUNCA guardada como precio real.
  En el interior el índice nacional es poco confiable; mejor pedir precio fresco
  que estimar.

### Conflicto de precios

- Ante dos precios distintos para el mismo producto y local en la misma ventana,
  gana el más nuevo.
- Puede no ser un error: un remarque (llegó mercadería nueva) hace que ambos
  hayan sido válidos en su momento. No se penaliza karma por esto.
- El conflicto manda el producto a una cola de validación prioritaria.

### Karma / reputación

- Se gana cargando bien y validando bien. También cuando otro valida como correcta
  una carga propia.
- Se pierde al acumular calificaciones negativas.
- Una validación solo cuenta en contra si cae dentro de la ventana de frescura.
  Fuera de eso es un precio nuevo, no una corrección.
- Las cargas de usuarios con karma bajo entran a validación con más lupa. Si
  resultan correctas, el premio de karma es mayor.

### Anti-spam

- No se puede identificar el hardware de forma confiable (limitación de iOS/Android).
  No intentarlo.
- Orden de defensa: (1) reputación de la cuenta, (2) attestation del dispositivo
  (Play Integrity / App Attest) para frenar emuladores y apps truchadas, (3) rate
  limiting y señales de comportamiento raro.
- La reputación vive en la cuenta, no en el dispositivo: un celular vendido no
  castiga al nuevo dueño.

### Medios de pago y recargo

- El precio que se carga es siempre el de góndola / lista (uno solo).
- Los medios de pago y recargos viven en el perfil del local, no en cada precio.
- Muchos locales de barrio cobran recargo por tarjeta (hasta 15-20%). Se captura
  a nivel local.
- Mini-encuesta opcional al salir del local ("¿te cobraron recargo?"): enriquece
  el catálogo de locales.
- Campos por medio de pago a nivel producto: futuro, no ahora.

### Ubicación

- Leer precios: desde cualquier lado, sin pedir ubicación.
- Cargar o validar precios: requiere estar cerca del local (geofence, ej. 150 m).
  Así se evita el ruido de gente cargando desde la casa.

## Principios de UX

- La app decide, el usuario confirma. Cada pregunta es fricción; sacar preguntas.
- Carga en 2-3 toques: detecta el local por ubicación, escanea, un solo campo
  (precio), confirma.
- Modo relevamiento: escanear-precio-escanear-precio en loop, para cargar varios
  productos en una vuelta al local.
- Recordar último local y productos. Alta de producto nuevo mínima.
- La falta de fricción empuja la carga correcta. Sumada a gamificación (futuro),
  arma un bucle de retroalimentación sano.

## Creación de locales

- Por ahora solo el admin crea locales (desde la app con superusuario estando en
  el local, o desde un navegador con mapa).
- Permite inventariar locales y sumar emprendimientos de comida.
- Abrir la creación a cualquiera es una puerta de spam: se evalúa a futuro si el
  proyecto crece.

## Fuera de alcance (futuro)

- Validación colaborativa completa y gamificación con recompensas.
- Modo offline y sync.
- Opiniones / calidad de producto (subjetivo).
- Apertura del alta de locales y del registro de usuarios.
- iOS.
- Orden por reputación del local y lista de **locales patrocinados** (un local
  paga para que su producto aparezca primero, siempre marcado «Patrocinado» y
  separado del ranking; nunca altera el mapa ni el «Más barato»). Propuesta
  técnica y UI de admin en `docs/04-plan-v0.0.2.md` (§5).
