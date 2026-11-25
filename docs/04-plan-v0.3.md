# Plan 0.3 — perfil, lista de compras y gamificación

Estado: **planificado** (2026-11-25), sin cortes definidos. Parte del 0.2.x (`docs/04-plan-v0.2.md`):
identidad recuperable y datos validados. Principios en `docs/10-roadmap.md`.

## Objetivo

Que la app sea útil **antes de ir al súper** y que cargar tenga un sentido visible: un lugar propio
(perfil), planificar una compra completa (lista) y reconocer a quien aporta (gamificación).

## Alcance (propuesto)

| Parte | Qué trae | Notas |
|-------|----------|-------|
| **Perfil** | Tab propio: karma, historial propio de cargas, avisos (`GET /v1/me/avisos` ya existe, falta su pantalla), cuenta y alias. | Cuenta ligada viene del 0.2. |
| **Lista de compras** | Tab propio: armar una lista y ver **qué local conviene para toda la lista**, con los mismos mínimos de datos y frescura que la línea de ahorro. Puede mostrar el ahorro **de la lista contra comprar todo en un solo local**, calculado solo con precios. | No hay ahorro acumulado ni «lo compré». Descuenta distancia (no mandar 3 km por unos pesos). |
| **Gamificación con recompensas** | Reconocimientos, niveles o logros ligados al karma y a la calidad de lo que se aporta. | Doc 1 la deja «fuera de alcance»: se diseña de cero al arrancar. Sin recompensas que premien spam. |
| **Precio relativo al promedio** | «Zona más barata» por producto normalizado (no comparar un aceite con un fideo). | Anotado en `docs/04-plan-v0.1.md` §11.6 como segunda etapa del dashboard; necesita volumen. |

## Decisiones abiertas
- Cómo se persiste la lista (¿solo en el celular, o en el servidor para recuperarla tras ligar la cuenta?).
- Qué es «conviene» en una lista: ¿un solo local o el reparto óptimo entre dos? (el segundo exige mucho
  más dato y más lógica).
- Qué se premia exactamente y qué se muestra a otros (privacidad: alias, nunca email).
- ¿La gamificación es pública (rankings) o privada? El dashboard de admin ya tiene rankings por alias.

## Fuera de este release
Notificaciones (0.4), offline (0.5), apertura y deploy (0.6).
