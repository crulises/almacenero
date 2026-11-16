.PHONY: up down migrate seed admin test lint build venv apk etl-off etl-off-muestra etl-off-descargar conflictos

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
	$(PY) -m pytest etl/tests -q
	cd app && flutter test

lint: $(PY)
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	$(VENV)/bin/ruff check --config backend/pyproject.toml etl && $(VENV)/bin/ruff format --check --config backend/pyproject.toml etl
	cd app && flutter analyze

build: ## Build de imágenes
	docker compose build

# --- ETL del catálogo (uno por fuente) ---------------------------------------
OFF_URL := https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz
OFF_ARCHIVO ?= etl/data/off.csv.gz

etl-off-muestra: ## Baja ~30 MB del principio del volcado de OFF (para probar)
	@mkdir -p etl/data
	curl -fL -r 0-30000000 -o etl/data/off-muestra.csv.gz $(OFF_URL)
	@echo "Listo: etl/data/off-muestra.csv.gz (truncado a propósito; el ETL lo tolera)"

etl-off-descargar: ## Baja el volcado COMPLETO de OFF (~1,5 GB). Pedí OK antes de correrlo
	@mkdir -p etl/data
	curl -fL -C - -o $(OFF_ARCHIVO) $(OFF_URL)

etl-off: $(PY) ## Carga OFF al catálogo: make etl-off [OFF_ARCHIVO=etl/data/off-muestra.csv.gz]
	@test -f $(OFF_ARCHIVO) || { echo "Falta $(OFF_ARCHIVO): make etl-off-muestra (chico) o make etl-off-descargar (completo)"; exit 1; }
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m etl.off $(OFF_ARCHIVO)

conflictos: $(PY) ## Lista los conflictos de catálogo pendientes de revisión
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m etl.conflictos

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
