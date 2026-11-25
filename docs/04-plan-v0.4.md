# Plan 0.4 — seguir productos y notificaciones

Estado: **planificado** (2026-11-25), sin cortes definidos. Parte del 0.3.x (`docs/04-plan-v0.3.md`):
perfil y lista de compras. Principios en `docs/10-roadmap.md`.

## Objetivo

Avisar cuando algo que le importa a la persona **baja de precio**, sin hacer spam: «pocas, útiles, con
tope» (principio 5 del roadmap).

## Alcance (propuesto)

| Parte | Qué trae |
|-------|----------|
| **Seguir productos** | Desde la ficha y desde el perfil: seguir/dejar de seguir un producto (y, a decidir, un local). |
| **Notificaciones push** | Aviso cuando un producto seguido baja dentro del radio de la persona, con mínimos de frescura y de baja relevante. Canal y proveedor (FCM u otro) a decidir; **nada acoplado a Supabase por nombre** (CLAUDE.md). |
| **Control** | Tope diario por usuario, silenciar por producto, apagar todo, y registro de lo enviado. Config del admin. |

## Decisiones abiertas
- Proveedor de push, y si hace falta un servicio propio para envío (costo bajo, hobby).
- Qué cuenta como «baja» (umbral por porcentaje, no por centavos) y cómo se evita avisar por un precio
  mal cargado: solo precios **validados** (0.2) o con frescura mínima.
- Permisos de Android 13+ para notificaciones y qué ve quien las rechaza (la app debe seguir siendo
  útil sin ellas).
- Privacidad: qué datos viajan al proveedor de push (ninguno personal más que el token).

## Fuera de este release
Offline (0.5), apertura y deploy (0.6).
