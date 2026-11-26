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

Orden sugerido: A → B → C → D (A habilita la identidad que C necesita; D usa lo validado).

### Parte A — decisiones tomadas (corte 21, 2026-11-26)

Diseño completo: `docs/superpowers/specs/2026-11-26-cuentas-ligables-design.md`. Resumen:

- Solo **Google** (el flujo email/contraseña queda para otro corte; iOS/Apple, para el 0.6).
- Ligar es **la misma cuenta** (mismo `usuarios.id`/`auth_id`). Entrar con una ya ligada desde otro celular
  funciona sin invitación; un Google nuevo pasa por las defensas del alta.
- La tarjeta «Protegé tu cuenta» sale con karma ≥ 3 (`karma_umbral_ligar_cuenta`) y «Luego» la oculta 7 días;
  desde «Acerca de › Cuenta» se puede ligar siempre.
- Las huérfanas las **reclama un admin** (nunca automático): suma karma, reasigna autoría, la huérfana queda
  `fusionada` (no `baja`, para no marcar el dispositivo).
- Perfil demográfico (nombre, sexo, nacimiento, país): no se pide acá (0.3).
- Android: `applicationId` `dev.crulises.almacenero`; el SHA-1 de la keystore de **release** se registra
  como otro cliente Android en Google Cloud al publicar (`docs/03`).

### Parte A — pendientes menores (anotados, no hechos)

| Qué | Por qué hace falta / qué mejora |
|---|---|
| Pantalla para el 403 `cuenta_fusionada` en la app | Hoy una cuenta fusionada ve «No pudimos conectar» sin salida. Con una pantalla propia («Esta cuenta se unió a otra: entrá con Google») y el botón «Entrar con Google», la persona no queda trabada. |
| `ya_ligada` (409) como éxito | Si se perdió la respuesta de un ligado anterior, la app dice «No pudimos ligar» aunque la cuenta ya está ligada. Debería refrescar y mostrar «Tu cuenta está ligada»: menos confusión y cero reintentos inútiles. |
| El PIN «pegado» al camino de Google | Tras tocar «Entrar con Google», todo PIN escrito va por Google aunque la persona quiera el alta anónima; si el `id_token` vence (~1 h) cada PIN falla. Un botón «Volver» y reiniciar el token pendiente evita el callejón. |
| Carreras reclamo ↔ carga / ligado de la huérfana | Una carga en vuelo de la huérfana puede quedar a su nombre tras el reclamo. Es raro (el admin reclama cuentas perdidas); se arregla bloqueando la fila en la carga. Mejora la integridad del karma, no la UI. |
| Rate limit propio en `/google/ligar` | Hoy depende de GoTrue. Con uno propio se corta antes el abuso desde una IP. |
| `proteger_estado` no cubre `fusionada_en` suelto | Dejaría cambiar el destino de una fusión sin pasar por el reclamo. Cerrarlo hace la fusión inalterable a mano; no cambia la UI. |

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
