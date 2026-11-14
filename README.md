# Almacenero

App móvil (Flutter, Android) para compartir precios de productos entre locales.
Ver `docs/01-producto-vision.md` y `docs/02-spec-tecnico.md`, y `CLAUDE.md` para
el alcance de v0.0.1.

## Requisitos

Docker, [Supabase CLI](https://supabase.com/docs/guides/cli), Python 3.10+,
Flutter, `psql`.

## Uso

```bash
make up       # Supabase local + backend (http://localhost:8000/docs)
make seed     # datos de arranque (las migraciones las aplica `supabase start`)
make test
make lint
make down
```

## Estructura

`app/` Flutter · `backend/` FastAPI · `supabase/` migraciones y seed ·
`etl/` pipeline OFF · `docs/` fuente de verdad.
