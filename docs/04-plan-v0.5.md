# Plan 0.5 — offline y productos pesables

Estado: **planificado** (2026-11-25), sin cortes definidos. Parte del 0.4.x (`docs/04-plan-v0.4.md`).
Principios en `docs/10-roadmap.md`.

## Objetivo

Que la app sirva **donde no hay señal** (dentro de muchos locales) y cubrir lo que hoy no tiene EAN
(frutas, verduras, fiambres a granel).

## Alcance (propuesto)

| Parte | Qué trae | Notas |
|-------|----------|-------|
| **Modo offline y sync** | Consultar precios ya vistos sin red y **cargar precios sin red** que se envían al volver la conexión. | Doc 1 lo deja fuera de alcance. Las «Recientes» del corte 20 y la cola de eventos del 19b ya son un primer paso (solo en el celular). Hay que resolver conflictos, orden e idempotencia de la carga. |
| **Productos pesables y genéricos** | Precio por kilo/litro para productos sin EAN (frutas, carne, fiambre) y productos «genéricos» (ej. «pan»). | El esquema ya los modela y están **desactivados por config** (CLAUDE.md, v0.0.1). Hay que decidir cómo se identifican sin código de barras. |

## Decisiones abiertas
- Qué parte del catálogo y de los precios se baja al celular (tamaño, antigüedad, zona) y cuándo se
  actualiza.
- Cómo se valida una carga hecha offline (geofence y hora: el celular puede mentir) sin abrir la puerta
  al spam; qué pasa si el local se verificó o cambió mientras tanto.
- Cómo se identifica y se busca un pesable: lista curada por el admin, categorías, búsqueda por nombre.
- Unidades y comparación: precio por kilo vs por unidad.

## Fuera de este release
Apertura al público y deploy (0.6).
