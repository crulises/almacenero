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

- `docs/08-estandares-de-carga.md` — estándares de carga del catálogo (los que cita el sistema
  cuando ajusta lo que cargó una persona; espejo de `backend/app/services/estandares.py`).
- `docs/09-formato-intercambio-catalogo.md` — formato `catalogo_curado_v1/v2` para intercambiar
  catálogos (autocontenido: se reutiliza en otro proyecto). Tocá `etl/curado/` solo de acuerdo a él.
- `docs/03-problemas-soluciones.md` — cómo armar el entorno desde cero y los
  problemas ya vividos (con su solución). **Leelo antes de debuggear un problema
  de entorno, de build o de auth**, y agregale lo nuevo que aparezca (formato
  Síntoma → Causa → Solución). No es fuente de verdad: si contradice al Doc 1 o 2,
  ganan ellos.

> **Versionado:** «v0.0.1» y «v0.0.2» son nombres históricos de **planes**; la 0.0.1 ya no está vigente
> y el próximo release es **0.1.x** (la validación colaborativa, 0.2.x o posterior). Ver Doc 2.
> **Zona horaria:** todo en UTC (`timestamptz`) y la hora local solo al mostrar (Doc 2, «Tiempo y zona
> horaria»). Corte 19 (dashboard de admin con eventos y mapa): planificado en `docs/04` §11; 19b (eventos desde la app) y 19a (dashboard: tarjetas, series, rankings, estrellas, zona horaria) ya están hechas; 19c (mapa, exportar/vaciar eventos, programación) también.

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

Toda la lógica operativa va en el Makefile. CI solo llama a estos targets. `make help` los lista con su
descripción (al agregar un target, ponele su `## descripción` en la misma línea).

- `make up` / `make down` — levanta / baja el stack local.
- `make migrate` — aplica migraciones.
- `make seed` — carga datos de arranque.
- `make test` — corre tests.
- `make lint` — linter.
- `make build` — build de imágenes.
- `make catalogo-calidad` / `make catalogo-renormalizar [APLICAR=1]` — mide / aplica el
  normalizador del catálogo (Doc 7).
- `make catalogo-csv-exportar` / `make catalogo-csv-exportar-base` / `make catalogo-csv-importar
  ARCHIVO=... [APLICAR=1]` — arma el CSV curado desde OFF/SEPA locales (reproducible) / vuelca el
  catálogo de la base con sus metadatos (formato v2, Doc 9) / lo valida en seco o lo importa (Doc 4
  §10-B). Los exports piden solo un **nombre** (sin extensión): dejan un `.zip` (CSV + `LEEME.txt`)
  en `ETL_EXPORT_DIR`.
- `make locales-exportar [TODOS=1]` / `make locales-importar ARCHIVO=... [APLICAR=1]` — llevan los
  locales verificados de una instalación a otra (Doc 9 §8).
- `make almacen-probar` / `make minio-up` / `make minio-down` — prueba el almacén de exportaciones (S3 o
  disco; Doc 4 §11.4) / levanta o baja MinIO, un S3 opcional para probar portabilidad.
- `make etl-worker` — worker local: toma de la cola (DATABASE_URL) los ETL pesados que se lanzan desde el
  panel web (sección ETL; Doc 4 §10-A).
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
