# Plan 0.6 — apertura al público

Estado: **planificado** (2026-11-25), sin cortes definidos. Parte del 0.5.x (`docs/04-plan-v0.5.md`).
Principios en `docs/10-roadmap.md`. Es el release en que la app deja de ser un grupo cerrado: **todo lo
que lo hace seguro tiene que estar antes** (identidad recuperable, validación, anti-spam, tiles propios).

## Objetivo

Abrir la app a más gente sin perder la calidad del dato ni gastar de más.

## Alcance (propuesto)

| Parte | Qué trae | Notas |
|-------|----------|-------|
| **Deploy** | Fly.io (2 servicios, scale-to-zero), Cloudflare (DNS y SSL; Access opcional para `/admin`), Supabase como base, secretos, rollback, simulacro de restauración. | Es el corte 10 (PR #19, **pausado y con conflictos con `main`**; base en `docs/06-deploy.md` de esa rama). Dominio `crulises.dev`: app en `almacenero.crulises.dev/admin`, API en `almacenero-api.crulises.dev`. `applicationId` `dev.crulises.almacenero`. No está atado a una versión de la app y puede hacerse antes si el dueño quiere. |
| **Tiles propios** | Proveedor/hosting propio (Protomaps/PMTiles en R2). | **Condición previa**: el OSM público solo vale para un grupo cerrado. |
| **Apertura de registros y alta de locales** | Dejar de pedir invitación; que cualquiera pueda dar de alta un local. | El Doc 1 hoy dice «solo el admin crea locales»; `config.alta_locales_abierta` es un interruptor de prueba. Revisar anti-spam, moderación y validación de locales. |
| **Patrocinio y orden por reputación** | Locales patrocinados siempre marcados, aparte del ranking; orden por reputación del local. | Diseño en `docs/04-plan-v0.1.md` §5. **Nunca altera el mapa ni el «Más barato»** ni ninguna recomendación (principio 2). |
| **iOS** | App iOS y OAuth con Apple ID. | Requiere Apple Developer (USD 99/año, Doc 2). |
| **Política de privacidad** | Redactarla (menciona el `ANDROID_ID` hasheado, los eventos y la ubicación). | Pendiente desde el corte 12. |

## Decisiones abiertas
- Estrategia de ramas, tags y versiones alineando `APP_VERSION`, tags de git y releases de Fly
  (pendiente desde el plan 0.1, «Abiertas»).
- Costos reales de hosting y almacenamiento con carga abierta; plan de escape si se llena Supabase.
- Si el deploy y la apertura van juntos o separados: el deploy puede adelantarse para probar en serio
  sin abrir los registros.

## Sin fecha
**Opiniones y calidad de producto** (Doc 1: subjetivo, fuera de alcance): no tiene diseño ni release
asignado.
