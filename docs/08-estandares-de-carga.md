# Doc 8 — Estándares de carga del catálogo

Qué se le pide a quien carga o corrige un producto (moderadores y admins) y a qué se refiere el
sistema cuando ajusta algo de lo que se cargó. Es la **ayuda de referencia**: el panel la
muestra en **Ayuda → Estándares de carga**, la API la expone en `GET /v1/ayuda/estandares` (la
app la usa en el corte 16) y los avisos al usuario la citan.

La fuente en código es `backend/app/services/estandares.py` (los `id` son estables); este
documento la espeja y `etl/tests/test_estandares.py` verifica que no se separen. Las reglas
mecánicas que las implementan están en el Doc 7 §4.

## Cómo se aplican

- Lo que una persona carga queda **bloqueado contra los ETL** (Doc 4 §10-D).
- Si el **nombre** no cumple el estándar (marca, tamaño o envase adentro, abreviaturas,
  mayúsculas corridas…), el normalizador lo **limpia** y **completa los campos que estaban
  vacíos** con lo que traía adentro. **Nunca pisa un campo que la persona ya cargó.** Pasa al
  correr `make catalogo-renormalizar APLICAR=1` (después, el botón de ETL del panel, corte 18).
- A quien cargó se le deja un **aviso** con el porqué y los estándares que no se cumplían
  (`GET /v1/me/avisos`). **Es solo informativo: no cambia el karma.**
- Lo que el normalizador no puede resolver no se inventa: queda **dudoso** y lo revisa una
  persona desde el tablero.

## Los estándares

| `id` | Estándar | Regla | Mal → bien |
|---|---|---|---|
| `nombre` | El nombre describe el producto | El nombre dice qué es. La marca, el tamaño y el envase van en sus campos. | «Aceite Cocinero Girasol 900 ml Botella» → «Aceite Girasol» · Cocinero · 900 ml · botella |
| `marca` | Marca en su campo y bien escrita | En el campo marca, con su escritura habitual. Sin saber o sin marca, vacío: nada de «S/d», «sin marca» ni razón social. | «CAÑUELAS S.A.», «S/d» → «Cañuelas», (vacío) |
| `tamano` | Tamaño: número y unidad, en su campo | Contenido total en g, kg, ml, l o u. El pack lleva la cantidad aparte y el tamaño es el total. «1 unidad» no es un tamaño. | «Gaseosa Naranja X 24x275ml» → pack de 24 · 6,6 l |
| `presentacion` | Presentación en su campo | El envase (botella, lata, caja, doypack, bolsa, paquete…) en minúscula, en su campo. | «Aceite de Oliva Extra Virgen PET» → …· pet |
| `abreviaturas` | Palabras completas, sin abreviaturas | Se escribe completo («para», «con», «sin», «extra virgen»). Las abreviaturas ambiguas nunca se dejan. | «Aceite Oliv EV p/ ensalada» → «Aceite Oliva Extra Virgen para ensalada» |
| `mayusculas` | Mayúsculas de título | Inicial mayúscula en cada palabra (salvo de, la, con, para, y, en, del, sin, al, por). Ni todo MAYÚSCULAS ni todo minúsculas. | «ACEITE DE GIRASOL» → «Aceite de Girasol» |
| `limpieza` | Sin códigos ni símbolos sueltos | Sin códigos internos, espacios dobles, caracteres raros ni puntuación suelta al final. | «000123 Fideos   Tirabuzón ..» → «Fideos Tirabuzón» |
| `no_inventar` | Solo lo que dice el envase | Se carga lo que se lee. Un dato desconocido se deja vacío: es mejor vacío que inventado. | Marca «Genérica» que no figura → vacía |

## Cuando haga falta citarlos

El aviso que recibe quien cargó dice, por ejemplo: «Ajustamos el nombre «Aceite Cocinero
Girasol 900 ml Botella» a «Aceite Girasol» porque no cumplía los estándares de carga: El
nombre describe el producto; Marca en su campo y bien escrita; … Es solo para que lo tengas
presente: no afecta tu karma.» Si algo del estándar no está claro o falta un caso, se agrega
acá y en `estandares.py`.
