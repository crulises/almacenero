.PHONY: up down migrate seed demo demo-borrar admin test lint build venv apk

SHELL := /bin/bash
VENV := backend/.venv
PY := $(VENV)/bin/python

# --- stack local -----------------------------------------------------------
up: ## Levanta Supabase (Postgres/Auth/Storage) y el backend
	@test -f .env || cp .env.example .env
	supabase start
	@# Completa AUTH_API_KEY (api key pública del auth local) si falta en .env.
	@if ! grep -qE '^AUTH_API_KEY=.+' .env; then \
		key=$$(supabase status -o json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['ANON_KEY'])"); \
		test -n "$$key" || { echo "no pude leer ANON_KEY de supabase status"; exit 1; }; \
		{ grep -v '^AUTH_API_KEY=' .env; echo "AUTH_API_KEY=$$key"; } > .env.tmp && mv .env.tmp .env; \
		echo "AUTH_API_KEY completada en .env"; \
	fi
	docker compose up -d --build backend

down: ## Baja todo
	docker compose down
	supabase stop

# --- base de datos ---------------------------------------------------------
migrate: ## Aplica migraciones pendientes
	supabase migration up

seed: ## Carga datos de arranque (idempotente)
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/seed.sql

demo: ## Datos de demo (3 locales con precios de distinta frescura) para ver el mapa
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/demo.sql

demo-borrar: ## Borra los datos de demo
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -c "delete from precios where local_id in (select id from locales where nombre like 'demo-%'); delete from locales where nombre like 'demo-%'; delete from precios where user_id in (select id from usuarios where alias = 'demo-usuario'); delete from usuarios where alias = 'demo-usuario';"

admin: ## Promueve a un usuario a admin: make admin ALIAS=anon-1ff221
	@test -n "$(ALIAS)" || { echo "Uso: make admin ALIAS=<alias del usuario>"; exit 1; }
	@# El rol está protegido por un trigger: se habilita solo dentro de esta transacción.
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -v alias="$(ALIAS)" <<< \
	"begin; select set_config('app.rol_write', 'on', true); update usuarios set rol = 'admin' where alias = :'alias'; commit;"

# --- calidad ---------------------------------------------------------------
$(PY):
	python3 -m venv $(VENV)
	$(PY) -m pip install -q -e "backend[dev]"

venv: $(PY)

test: $(PY) ## Tests de backend (Postgres local real) y de la app
	cd backend && .venv/bin/python -m pytest
	cd app && flutter test

lint: $(PY)
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd app && flutter analyze

build: ## Build de imágenes
	docker compose build

# --- app en un celular -----------------------------------------------------
apk: ## APK debug (arm64) para probar en un celular de la misma red Wi-Fi
	@# El celular no puede usar 10.0.2.2 (solo existe en el emulador): la app apunta
	@# a la IP de esta máquina. Se puede forzar con `make apk LAN_IP=192.168.1.50`.
	@ip="$(LAN_IP)"; \
	[ -n "$$ip" ] || ip=$$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | cut -d' ' -f1); \
	[ -n "$$ip" ] || { echo "No pude detectar la IP local: usá make apk LAN_IP=<ip>"; exit 1; }; \
	echo "La app apuntará a http://$$ip:8000"; \
	cd app && flutter build apk --debug --target-platform android-arm64 --dart-define=API_URL=http://$$ip:8000 \
	&& echo "APK: app/build/app/outputs/flutter-apk/app-debug.apk"
