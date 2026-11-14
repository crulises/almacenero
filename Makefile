.PHONY: up down migrate seed test lint build venv

SHELL := /bin/bash
VENV := backend/.venv
PY := $(VENV)/bin/python

# --- stack local -----------------------------------------------------------
up: ## Levanta Supabase (Postgres/Auth/Storage) y el backend
	@test -f .env || cp .env.example .env
	supabase start
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
