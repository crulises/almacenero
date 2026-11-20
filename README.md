# Almacenero

App móvil (Flutter, Android) para compartir precios de productos entre locales.
Ver `docs/01-producto-vision.md` y `docs/02-spec-tecnico.md`, y `CLAUDE.md` para
el alcance de v0.0.1.

## Requisitos

Docker, [Supabase CLI](https://supabase.com/docs/guides/cli), Python 3.10+,
Flutter, `psql`.

> ¿Entorno nuevo o algo no anda? Mirá
> [`docs/03-problemas-soluciones.md`](docs/03-problemas-soluciones.md): pasos para
> armar todo desde cero y los problemas ya resueltos.

## Uso

```bash
make up       # Supabase local + backend (http://localhost:8000/docs) + panel de admin (http://localhost:8080)
make admin-crear EMAIL=vos@mail.com   # crea el admin del panel (pide la contraseña)
make seed     # datos de arranque (las migraciones las aplica `supabase start`)
make test
make lint
make down
make apk      # APK para el celular (misma red Wi-Fi, backend en `make up`); sube la versión sola y la muestra en la app
```

## Estructura

`app/` Flutter · `backend/` FastAPI · `supabase/` migraciones y seed ·
`etl/` pipeline OFF · `docs/` fuente de verdad.
