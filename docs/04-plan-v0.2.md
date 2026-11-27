# Plan 0.2 — confianza y frescura

Estado: **planificado** (2026-11-25); los cortes se definen al arrancar el release con el dueño (empiezan en
el corte 21). Parte del 0.1.x cerrado (`docs/04-plan-v0.1.md`, corte 20). Ante una duda de
comportamiento gana el Doc 1; ante una duda técnica, el Doc 2. Principios en `docs/10-roadmap.md`.

## Objetivo

Que el dato se pueda **creer**. Con pocos usuarios la frescura no está garantizada (la preocupación del
dueño): hay que **dirigir** las cargas hacia lo que falta y hacia lo viejo, dar a cada persona una
identidad recuperable, y que otros puedan confirmar un precio. Y empezar a dar una guía útil con lo que
ya se sabe (la línea de ahorro en la ficha).

## Alcance (propuesto)

| # | Parte | Qué trae | Depende de |
|---|-------|----------|-----------|
| A | **Cuentas ligables** | Ligar la cuenta anónima a **email y Google**, para recuperarla tras reinstalar o en otro celular y para abrir sesión con otra cuenta. Hoy «Otras cuentas en el mismo dispositivo» (panel) son cuentas anónimas huérfanas: no hay forma de volver a ellas. OAuth hoy está «cableado y apagado» (Doc 1, «Identidad»). | — |
| B | **Precios por refrescar** | Lista, para el local donde estás, de los productos con precio viejo (más de N días) o sin precio, **priorizada por lo que más se consulta** (`eventos`, corte 19b). Refrescar vale más karma que cargar algo fresco. | 19b |
| C | **Validación colaborativa y cola** | Una persona confirma o desmiente el precio que cargó otra; la cola de validación; la tarjeta «precios validados» del dashboard (hoy en 0). Afecta al karma. | A |
| D | **Línea de ahorro en la ficha** | «Ahorrás 12% yendo a X». Solo con mínimos de datos, frescura y descontando la distancia. **No acumula nada.** | C (confianza del dato) |

| 22 | **Historial de precios por local** | Pantalla desde la ficha: el precio de un producto en un local (el más cercano, cambiable) con gráfico lineal, mapa «Vos»/«Local» y variación contra el precio anterior. Transparencia: ver si un descuento es real. | — |
| 23 | **Hitos en el gráfico** | Marcas manuales («Aumento de combustibles 30%») cargadas desde el panel de admin y dibujadas como líneas verticales. Globales por defecto, acotables por rubro/categoría; varios el mismo día → la app toma uno al azar. | 22 |

Orden sugerido: A → B → C → D (22 y 23 son independientes de ese orden) (A habilita la identidad que C necesita; D usa lo validado).

## Corte 22: historial por local (hecho, falta probarlo en el celular)

Diseño: `docs/superpowers/specs/2026-11-26-historial-por-local-design.md`; plan:
`docs/superpowers/plans/2026-11-26-historial-por-local.md`. Detalle técnico en el Doc 2.

**Qué probar en el celular:**
1. Entrar a un producto con precios y tocar «Ver historial por local» (está encima de «Cargar precio»).
2. Se abre en **Gráfico**: línea con el precio en el tiempo; **Mapa**: «Local» y «Vos».
3. El título es el local más cercano con su distancia; tocarlo para cambiar de local (ordenados por
   distancia; los que no tienen precios dicen «sin precios»).
4. Cada fila dice cuánto subió o bajó contra el anterior.
5. Elegir un local sin precios: mensaje, «Ir al inicio» y «Escanear».
6. «Escanear otro» (arriba a la derecha) y, con el GPS apagado, que igual cargue (sin distancia ni «Vos»).

**Corte 23 (hitos), pendiente:** tabla `hitos` (fecha, texto, categorías), alta/edición en el panel de
admin y lectura para la app. Las categorías/rubros del catálogo aún no existen: tendrán que ser
editables y un producto podrá tener varias (muchos a muchos); hasta entonces el filtro se guarda pero no
aplica.

## Reglas que ya están decididas (de `docs/10-roadmap.md`)

1. La app es **guía, no tracker financiero**: sin «lo compré», sin ahorro acumulado.
2. **El orden de los precios no se vende**: una recomendación se calcula solo con precios.
3. **Nunca mostrar vacío**: sin precio → «Sé el primero en cargarlo» (ya hecho en el corte 20).
4. Mostrar el límite de lo que se sabe: frescura y distancia siempre visibles.
5. Karma: refrescar y cubrir lo que falta valen más; **nada de premiar spam** (anti-spam del corte 9).

## Decisiones abiertas (a cerrar en el brainstorming de cada parte)

- **A.** ¿Qué pasa con la cuenta anónima al ligarse (se conserva el mismo `usuario`)? ¿Se permite abrir
  sesión con una cuenta ya ligada desde un celular donde ya hay otra? Qué hacer con las «huérfanas»
  existentes. Cómo se mezcla con `ANDROID_ID` y las bajas (Doc 4 §9 del plan 0.1).
- **B.** El umbral N (¿por categoría?), cómo se mide «lo más consultado» y cómo se evita que la cola se
  vuelva un incentivo a cargar basura.
- **C.** Cuántas confirmaciones hacen falta, qué hace una discrepancia, qué karma da validar y qué
  pasa si valida alguien con karma bajo o del mismo dispositivo.
- **D.** Los mínimos exactos (cantidad de precios, antigüedad, distancia) y cómo se muestra «no hay
  datos suficientes».

## Fuera de este release
Perfil, lista de compras y gamificación (0.3); notificaciones (0.4); offline (0.5); apertura, deploy,
tiles propios y patrocinio (0.6).
