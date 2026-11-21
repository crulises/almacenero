# CLAUDE.md

Guía para agentes (Claude Code) que trabajan en este repositorio.

## Qué es esto

App móvil (Flutter, Android primero) para compartir precios de productos entre
locales comerciales. Un grupo de usuarios carga precios de forma colaborativa, y
entre todos mapean el precio de un mismo artículo en varios locales sin tener que
recorrerlos. Proyecto hobby, bajo costo, pensado para escalar.

Antes de escribir código, leé:

- `docs/01-producto-vision.md` — qué hace el producto y cómo se debe comportar.
- `docs/02-spec-tecnico.md` — arquitectura, stack y decisiones técnicas.

Estos dos documentos son la fuente de verdad. Ante una duda de comportamiento,
gana el Doc 1. Ante una duda técnica, gana el Doc 2.

Además:

- `docs/03-problemas-soluciones.md` — cómo armar el entorno desde cero y los
  problemas ya vividos (con su solución). **Leelo antes de debuggear un problema
  de entorno, de build o de auth**, y agregale lo nuevo que aparezca (formato
  Síntoma → Causa → Solución). No es fuente de verdad: si contradice al Doc 1 o 2,
  ganan ellos.

## Alcance de v0.0.1 (NO te pases de esto)

Dentro:

- Auth anónima.
- Un solo local (el del admin).
- Escanear código de barras (EAN) y buscar contra el catálogo canónico.
- Cargar un precio para un producto en ese local.
- Ver el historial de precios de un producto.
- Karma básico por carga.

Fuera (NO implementar todavía, aunque se modele o se deje el cableado):

- Validación colaborativa y cola de validación.
- Gamificación / recompensas.
- Modo offline y sync.
- Múltiples locales y alta de locales.
- iOS.
- OAuth (dejar el cableado preparado, pero NO activarlo).
- Productos pesables / genéricos (modelar en el esquema, pero desactivados por config).

## Alcance de v0.0.2 (en curso)

Plan en `docs/04-plan-v0.0.2.md`: roles y alta de local (corte 5), geofence,
panel web de admin (corte 11), ETL por fuente, frescura visible, anti-spam, moderación
por karma y baja de cuentas (corte 12, `docs/04` §9) y preparación del release. El Doc 1
sigue mandando: el alta de locales por cualquier usuario es solo un interruptor de
prueba (`config.alta_locales_abierta`).

## Stack

- App: Flutter (Android).
- Backend: FastAPI (Python), API REST versionada `/v1`.
- Datos: PostgreSQL (provisto por Supabase, modo headless) con PostGIS.
- Auth: Supabase Auth (GoTrue). El backend valida el JWT.
- Storage: Supabase Storage (S3-compatible).
- Dev local: Supabase CLI (stack en Docker) + backend containerizado.

## Reglas de arquitectura

- La lógica de **integridad** vive en Postgres (constraints, checks, triggers).
- La lógica de **negocio** vive en el backend FastAPI. NO la pongas en Postgres.
- El cliente Flutter habla SOLO con el backend, nunca directo a Supabase/PostgREST.
- Nada de código acoplado a Supabase por nombre: usá `DATABASE_URL` y una capa
  `db` genérica.
- Migraciones = SQL plano, portables a cualquier Postgres.

## Estructura del repo

```
app/          Flutter (Android)
backend/      FastAPI
supabase/     config.toml, migrations/, seed.sql
etl/          pipeline de Open Food Facts
admin-web/    panel web de admin (nginx + HTML/JS estático, habla solo con /v1/admin)
docs/         01-producto-vision.md, 02-spec-tecnico.md, 03-problemas-soluciones.md
CLAUDE.md
README.md
Makefile
.env.example
```

La carpeta `supabase/` es requisito del CLI, no acoplamiento. El código propio
usa `DATABASE_URL` y una capa `db` genérica.

## Comandos (Makefile)

Toda la lógica operativa va en el Makefile. CI solo llama a estos targets.

- `make up` / `make down` — levanta / baja el stack local.
- `make migrate` — aplica migraciones.
- `make seed` — carga datos de arranque.
- `make test` — corre tests.
- `make lint` — linter.
- `make build` — build de imágenes.
- `make catalogo-calidad` / `make catalogo-renormalizar [APLICAR=1]` — mide / aplica el
  normalizador del catálogo (Doc 7).
- `make admin-crear EMAIL=...` — crea/promueve un admin con email y contraseña para el panel
  web (http://localhost:8080; `make admin-web` lo reconstruye).
- `make apk` — APK debug para probar en un celular de la misma red (apunta a la
  IP local de esta máquina; `LAN_IP=...` para forzarla).

## Convenciones

- API versionada: `/v1/...`.
- Secrets: `.env` local (NUNCA commitear) + secrets de plataforma en prod. Hay `.env.example`.
- Logs: structured logging simple.
- Tests: backend con pytest contra Postgres local real (no mocks). Flutter: unit + widget.

## Git y CI

- Remoto en GitHub.
- CI: GitHub Actions, que solo llama a targets del Makefile (lint + test en cada PR).
- Deploy manual al principio.
