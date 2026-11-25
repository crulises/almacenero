# Plan — cambiar el alias

Diseño: `docs/superpowers/specs/2026-11-25-alias-editable-design.md`. Cada paso: test que falla → código → verde.

1. **Migración** `20261203000001_alias_historial.sql`: tabla append-only, trigger, backfill, índice único parcial. Tests de integridad (`backend/tests/test_alias.py`).
2. **Servicio** `backend/app/services/alias.py`: normalizar, validar (formato, reservados, bloqueados), permiso por rol (`config`), tope diario, cambiar con actor/origen. Reglas con mensaje en `reglas.py`; defaults en `services/config.py` y `seed.sql`.
3. **Endpoint** `POST /v1/me/alias` y `puede_cambiar_alias` en `/me`.
4. **Admin**: el PATCH existente usa el servicio; la ficha suma `alias_historial`.
5. **Panel web** (`admin-web/`): sección «Alias anteriores» en la ficha del usuario.
6. **App**: `UserRepository.cambiarAlias`, `AppDeps.cambiarAlias`, lápiz y edición en `HomeScreen` + tests de widget.
7. **Docs** (Doc 2, Doc 4, Doc 3 si aparece algo), `make lint`, `make test`, PR sin mergear.
