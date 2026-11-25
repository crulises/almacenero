.PHONY: almacen-probar s3-alt-up s3-alt-down help backup restore-test up down migrate seed demo demo-borrar admin admin-crear admin-web invitacion test lint build venv apk etl-off etl-off-muestra etl-off-descargar etl-sepa etl-sepa-descargar etl-sepa-locales etl-osm etl-osm-descargar conflictos catalogo-calidad catalogo-renormalizar catalogo-csv-exportar catalogo-csv-exportar-base catalogo-csv-importar locales-exportar locales-importar etl-worker

SHELL := /bin/bash
VENV := backend/.venv
PY := $(VENV)/bin/python

# `make help` arma la lista leyendo los comentarios `## ...` de cada target y los títulos
# `# --- sección ---`: para que una descripción aparezca, escribila en la línea del target.
help: ## Lista todos los targets con lo que hace cada uno
	@awk 'BEGIN { FS = ":.*## " } \
		/^# --- .* ---/ { sec = $$0; gsub(/^# --- | -+$$/, "", sec); printf "\n\033[1m%s\033[0m\n", sec } \
		/^[a-zA-Z0-9_-]+:.*## / { printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo
	@echo "Los parámetros se pasan así: make admin-crear EMAIL=vos@mail.com (están en cada descripción)."

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
	@# Completa el almacén de exportaciones (Storage S3 local de Supabase) si .env no lo define.
	@if ! grep -qE '^EXPORT_S3_ENDPOINT=.+' .env; then \
		supabase status -o json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('EXPORT_S3_ENDPOINT='+d['STORAGE_S3_URL']); print('EXPORT_S3_ENDPOINT_DOCKER='+d['STORAGE_S3_URL'].replace('127.0.0.1','host.docker.internal')); print('EXPORT_S3_BUCKET=exportaciones'); print('EXPORT_S3_KEY='+d['S3_PROTOCOL_ACCESS_KEY_ID']); print('EXPORT_S3_SECRET='+d['S3_PROTOCOL_ACCESS_KEY_SECRET']); print('EXPORT_S3_REGION='+d['S3_PROTOCOL_REGION'])" >> .env \
			&& echo "Almacén de exportaciones (Storage local) completado en .env" || echo "(no pude leer el S3 local: los exports van al disco)"; \
	fi
	docker compose up -d --build backend admin-web
	@echo "Panel de admin: http://localhost:8080  (crear el admin: make admin-crear EMAIL=vos@mail.com)"

down: ## Baja todo
	docker compose down
	supabase stop

# --- base de datos ---------------------------------------------------------
migrate: ## Aplica migraciones pendientes
	supabase migration up

seed: ## Carga datos de arranque (idempotente)
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/seed.sql

demo: ## Datos de demo (3 locales con precios) cerca de LAT/LNG o del último local cargado a mano
	@# Sin LAT/LNG usa el último local creado por un usuario (el que cargaste vos);
	@# si no hay ninguno, el Obelisco de Buenos Aires.
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	lat="$(LAT)"; lng="$(LNG)"; \
	if [ -z "$$lat" ] || [ -z "$$lng" ]; then \
		p=$$(psql "$$DATABASE_URL" -tA -F' ' -c "select st_y(ubicacion::geometry), st_x(ubicacion::geometry) from locales where creado_por is not null and nombre not like 'demo-%' order by created_at desc limit 1"); \
		lat=$$(echo $$p | cut -d' ' -f1); lng=$$(echo $$p | cut -d' ' -f2); \
	fi; \
	[ -n "$$lat" ] || { lat=-34.6037; lng=-58.3816; }; \
	echo "Demo cerca de $$lat, $$lng"; \
	psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -v lat=$$lat -v lng=$$lng -f supabase/demo.sql

demo-borrar: ## Borra los datos de demo
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -c "delete from precios where local_id in (select id from locales where nombre like 'demo-%'); delete from locales where nombre like 'demo-%'; delete from precios where user_id in (select id from usuarios where alias = 'demo-usuario'); delete from usuarios where alias = 'demo-usuario';"

admin: ## Promueve a un usuario a admin: make admin ALIAS=anon-1ff221
	@test -n "$(ALIAS)" || { echo "Uso: make admin ALIAS=<alias del usuario>"; exit 1; }
	@# El rol está protegido por un trigger: se habilita solo dentro de esta transacción.
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -v alias="$(ALIAS)" <<< \
	"begin; select set_config('app.rol_write', 'on', true); update usuarios set rol = 'admin' where alias = :'alias'; commit;"

invitacion: ## Crea un código de invitación: make invitacion CODIGO=grupo [USOS=50] [DIAS=30]
	@test -n "$(CODIGO)" || { echo "Uso: make invitacion CODIGO=<código> [USOS=<máx>] [DIAS=<vigencia>]"; exit 1; }
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -v codigo="$(CODIGO)" -v usos="$(USOS)" -v dias="$(DIAS)" -c \
	"insert into invitaciones (codigo, usos_max, vence) values (lower(btrim(:'codigo')), nullif(:'usos','')::int, now() + (nullif(:'dias','') || ' days')::interval) returning codigo, usos_max, vence"

admin-crear: $(PY) ## Crea/promueve un admin con email y contraseña para el panel web: make admin-crear EMAIL=vos@mail.com [PASSWORD=...]
	@test -n "$(EMAIL)" || { echo "Uso: make admin-crear EMAIL=<email> [PASSWORD=<contraseña>] (sin PASSWORD la pide)"; exit 1; }
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m app.admin_cli "$(EMAIL)" $(if $(PASSWORD),"$(PASSWORD)")

admin-web: ## Reconstruye y levanta solo el panel web (http://localhost:8080)
	docker compose up -d --build admin-web
	@echo "Panel de admin: http://localhost:8080"

# --- backup y plan de escape (docs/04, «Plan de escape») -------------------
# Tablas cuyo conteo se registra al hacer el backup y se verifica al restaurar.
CONTEOS := locales productos_canonicos precios usuarios
BACKUP_DIR ?= backups

backup: ## pg_dump de la base (DATABASE_URL) a backups/almacenero-<fecha>.dump (carpeta ignorada por git)
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	set -e; mkdir -p $(BACKUP_DIR); \
	f=$(BACKUP_DIR)/almacenero-$$(date +%Y%m%d-%H%M%S).dump; \
	pg_dump "$$DATABASE_URL" --format=custom --schema=public --exclude-table=spatial_ref_sys --no-owner --no-privileges --file="$$f"; \
	for t in $(CONTEOS); do echo "$$t $$(psql "$$DATABASE_URL" -tA -c "select count(*) from $$t")"; done > "$$f.conteos"; \
	echo "Backup: $$f ($$(du -h "$$f" | cut -f1))"; cat "$$f.conteos"

restore-test: ## Simulacro: restaura el último backup en una base TEMPORAL (se crea y se borra) y compara conteos
	@# Nunca toca la base real: crea `almacenero_restore_test` en el mismo servidor, restaura
	@# ahí y la borra al terminar (también si algo falla). Funciona con el Postgres de `make up`.
	@# El grep saca un SET que agrega pg_dump 17 (no existe en servidores 15/16) y el CREATE SCHEMA public (ya existe).
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	set -e; \
	f=$$(ls -1t $(BACKUP_DIR)/*.dump 2>/dev/null | head -1); \
	test -n "$$f" || { echo "No hay backups en $(BACKUP_DIR)/: corré make backup"; exit 1; }; \
	base=$${DATABASE_URL%%\?*}; tmp=almacenero_restore_test; \
	admin=$${base%/*}/postgres; url=$${base%/*}/$$tmp; \
	[ "$${base##*/}" != "$$tmp" ] || { echo "DATABASE_URL apunta a la base temporal: abortando"; exit 1; }; \
	trap 'psql "$$admin" -q -c "drop database if exists $$tmp" >/dev/null' EXIT; \
	psql "$$admin" -q -c "drop database if exists $$tmp" -c "create database $$tmp"; \
	echo "Restaurando $$f en $$tmp..."; \
	psql "$$url" -q -c "create extension if not exists postgis" -c "create extension if not exists pg_trgm" -c "create extension if not exists unaccent"; \
	pg_restore --no-owner --no-privileges -f - "$$f" | grep -Ev '^(SET transaction_timeout|CREATE SCHEMA public;)' | psql "$$url" -q -v ON_ERROR_STOP=1 --single-transaction -o /dev/null; \
	ok=1; \
	while read -r t esperado; do \
		real=$$(psql "$$url" -tA -c "select count(*) from $$t"); \
		if [ "$$real" = "$$esperado" ]; then echo "OK   $$t: $$real"; else echo "FALLA $$t: restauradas $$real, el backup tenía $$esperado"; ok=0; fi; \
	done < "$$f.conteos"; \
	[ $$ok = 1 ] && echo "Simulacro OK: el backup se restaura completo" || { echo "Simulacro FALLÓ"; exit 1; }

# --- calidad ---------------------------------------------------------------
$(PY):
	python3 -m venv $(VENV)
	$(PY) -m pip install -q -e "backend[dev,etl]"

venv: $(PY) ## Crea el entorno virtual de Python (backend/.venv) con las dependencias

test: $(PY) ## Tests de backend (Postgres local real) y de la app
	cd backend && .venv/bin/python -m pytest
	$(PY) -m pytest etl/tests -q
	cd app && flutter test

lint: $(PY) ## Linter: ruff (backend y etl) y flutter analyze
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

# Países de OFF que se cargan: Argentina y sus vecinos (SEPA es la fuente principal
# para Argentina). OFF_PAISES= (vacío) carga todo el mundo (~2,4 GB en la base).
OFF_PAISES ?= en:argentina,en:paraguay,en:brazil,en:chile,en:uruguay,en:bolivia

etl-off: $(PY) ## Carga OFF al catálogo: make etl-off [OFF_ARCHIVO=...] [OFF_PAISES=]
	@test -f $(OFF_ARCHIVO) || { echo "Falta $(OFF_ARCHIVO): make etl-off-muestra (chico) o make etl-off-descargar (completo)"; exit 1; }
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m etl.off $(OFF_ARCHIVO) --paises "$(OFF_PAISES)"

SEPA_DIR ?= etl/data/sepa
# Día de SEPA a bajar (lunes..domingo); el id de recurso de cada día está en la ficha
# del dataset: https://datos.produccion.gob.ar/dataset/sepa-precios
SEPA_URL ?=

etl-sepa-descargar: ## Baja un zip diario de SEPA: make etl-sepa-descargar SEPA_URL=<url del recurso> (reintenta; el servidor corta)
	@test -n "$(SEPA_URL)" || { echo "Uso: make etl-sepa-descargar SEPA_URL=<url .zip de datos.produccion.gob.ar>"; exit 1; }
	@mkdir -p $(SEPA_DIR)
	@f=$(SEPA_DIR)/$$(basename "$(SEPA_URL)"); \
	for i in 1 2 3 4 5; do \
		curl -fL --max-time 1800 -A "almacenero-etl/0.1" -o "$$f" "$(SEPA_URL)" && unzip -tq "$$f" >/dev/null 2>&1 && { echo "OK: $$f"; exit 0; }; \
		echo "intento $$i falló, reintento..."; \
	done; echo "no se pudo bajar un zip válido"; exit 1

etl-sepa: $(PY) ## Carga SEPA al catálogo: make etl-sepa SEPA_ARCHIVOS="etl/data/sepa/sepa_domingo.zip"
	@test -n "$(SEPA_ARCHIVOS)" || { echo "Uso: make etl-sepa SEPA_ARCHIVOS=\"ruta1.zip ruta2.zip\""; exit 1; }
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m etl.sepa $(SEPA_ARCHIVOS)

etl-sepa-locales: $(PY) ## Carga las sucursales de SEPA como locales: make etl-sepa-locales [SEPA_ARCHIVOS=...] [PROVINCIA=misiones]
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m etl.sepa.locales $(or $(SEPA_ARCHIVOS),$(SEPA_DIR)/sepa_domingo.zip) $(if $(PROVINCIA),--provincia $(PROVINCIA))

OSM_URL ?= https://download.geofabrik.de/south-america/argentina-latest.osm.pbf
OSM_ARCHIVO ?= etl/data/osm/argentina-latest.osm.pbf

etl-osm-descargar: ## Baja el extracto de Argentina de Geofabrik (~440 MB; Geofabrik no parte por provincia)
	@mkdir -p etl/data/osm
	curl -fL --retry 5 -C - -o $(OSM_ARCHIVO) $(OSM_URL)

etl-osm: $(PY) ## Carga supermercados/almacenes de OSM como locales: make etl-osm PROVINCIA=misiones
	@test -n "$(PROVINCIA)" || { echo "Uso: make etl-osm PROVINCIA=misiones (slug o código AR-N)"; exit 1; }
	@test -f $(OSM_ARCHIVO) || { echo "Falta $(OSM_ARCHIVO): make etl-osm-descargar"; exit 1; }
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m etl.osm $(OSM_ARCHIVO) --provincia $(PROVINCIA)

conflictos: $(PY) ## Lista los conflictos de catálogo pendientes de revisión
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m etl.conflictos

catalogo-calidad: $(PY) ## Mide la calidad del catálogo con el normalizador (no escribe): make catalogo-calidad [MUESTRA=20] [ESTADO=dudoso]
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m etl.calidad --muestra $(or $(MUESTRA),0) $(if $(ESTADO),--estado $(ESTADO))

catalogo-renormalizar: $(PY) ## Normaliza TODO el catálogo y recalcula la calidad (Doc 7). Simulacro; con APLICAR=1 escribe
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m etl.renormalizar $(if $(APLICAR),--aplicar)

# --- CSV curado (docs/04 §10-B) ----------------------------------------------
# El CSV curado es un extracto ya normalizado de las fuentes crudas: se arma una vez en tu
# máquina (reproducible: mismas fuentes + normalizador = mismo hash) y se importa donde haga
# falta, sin volver a bajar OFF entero. El archivo se puede borrar tras importarlo.
# Solo un NOMBRE (sin carpeta ni extensión): el export es un .zip con los datos y un LEEME.txt,
# y va a ETL_EXPORT_DIR (por defecto etl/data/exports/).
CURADO_SALIDA ?= catalogo-curado
SEPA_MIN_FILAS ?= 1

catalogo-csv-exportar: $(PY) ## Arma el CSV curado desde OFF/SEPA locales: make catalogo-csv-exportar [CURADO_SALIDA=...] [OFF_ARCHIVO=...] [SEPA_ARCHIVOS="a.zip b.zip"] [OFF_PAISES=] [SEPA_MIN_FILAS=1]
	@test -f "$(OFF_ARCHIVO)" -o -n "$(SEPA_ARCHIVOS)" || { echo "Falta una fuente: OFF_ARCHIVO=... (make etl-off-muestra) y/o SEPA_ARCHIVOS=\"a.zip\""; exit 1; }
	$(PY) -m etl.curado.exportar $(CURADO_SALIDA) $(if $(wildcard $(OFF_ARCHIVO)),--off $(OFF_ARCHIVO)) \
		$(if $(SEPA_ARCHIVOS),--sepa $(SEPA_ARCHIVOS)) --paises "$(OFF_PAISES)" --sepa-min-filas $(SEPA_MIN_FILAS)

catalogo-csv-exportar-base: $(PY) ## Vuelca el catálogo de la base al formato de intercambio v2 (con metadatos): make catalogo-csv-exportar-base [CURADO_SALIDA=nombre]
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m etl.curado.exportar_base $(CURADO_SALIDA)

catalogo-csv-importar: $(PY) ## Valida (simulacro) o importa un CSV curado: make catalogo-csv-importar ARCHIVO=... [APLICAR=1] [FORZAR=1]
	@test -n "$(ARCHIVO)" || { echo "Uso: make catalogo-csv-importar ARCHIVO=<csv curado> [APLICAR=1] [FORZAR=1]"; exit 1; }
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m etl.curado.importar "$(ARCHIVO)" $(if $(APLICAR),--aplicar) $(if $(FORZAR),--forzar)

# Locales verificados para llevar a otra instalación (docs/09 §8): mismo esquema de nombre/zip.
LOCALES_SALIDA ?= locales-intercambio

locales-exportar: $(PY) ## Vuelca los locales verificados a un .zip: make locales-exportar [LOCALES_SALIDA=nombre] [TODOS=1]
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m etl.locales_intercambio exportar $(LOCALES_SALIDA) $(if $(TODOS),--todos)

locales-importar: $(PY) ## Valida (simulacro) o importa un export de locales: make locales-importar ARCHIVO=... [APLICAR=1]
	@test -n "$(ARCHIVO)" || { echo "Uso: make locales-importar ARCHIVO=<zip de locales> [APLICAR=1]"; exit 1; }
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m etl.locales_intercambio importar "$(ARCHIVO)" $(if $(APLICAR),--aplicar)

# --- ETL desde el panel (docs/04 §10-A) ---------------------------------------
etl-worker: $(PY) ## Worker local: toma de la cola de la base (DATABASE_URL, local o remota) los ETL pesados que lanzás desde el panel
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m etl.worker

# --- almacén de exportaciones (docs/04 §11.4) ----------------------------------
almacen-probar: $(PY) ## Ida y vuelta con el almacén configurado (EXPORT_S3_* o disco): sube, relee, compara y borra un archivo de prueba
	@set -a; . ./.env 2>/dev/null || . ./.env.example; set +a; \
	$(PY) -m etl.almacen_probar

s3-alt-up: ## Levanta un S3 alternativo opcional (SeaweedFS) en :8333 para probar que el almacén no depende de Supabase
	docker compose --profile s3-alt up -d s3-alt
	@echo "S3 alternativo: http://localhost:8333 (cualquier clave sirve; sin consola)."
	@echo "Para usarlo: poné en .env EXPORT_S3_ENDPOINT=http://127.0.0.1:8333, EXPORT_S3_BUCKET=exportaciones,"
	@echo "EXPORT_S3_KEY=almacenero y EXPORT_S3_SECRET=almacenero-dev-secreto; después: make almacen-probar"

s3-alt-down: ## Baja el S3 alternativo (los datos quedan en el volumen s3-alt-datos)
	docker compose --profile s3-alt stop s3-alt

# --- app en un celular -----------------------------------------------------
# API_TIMEOUT_S=40 make apk -> espera 40 s por intento (default de la app: 20 s).
apk: ## APK debug (arm64) para el celular: sube la versión sola (0.0.1, 0.0.2, ...) y la muestra en la app
	@# El celular no puede usar 10.0.2.2 (solo existe en el emulador): la app apunta
	@# a la IP de esta máquina. Se puede forzar con `make apk LAN_IP=192.168.1.50`.
	@# La versión (serie del pubspec + contador local) la calcula app/tool/version.sh.
	@ip="$(LAN_IP)"; \
	[ -n "$$ip" ] || ip=$$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | cut -d' ' -f1); \
	[ -n "$$ip" ] || { echo "No pude detectar la IP local: usá make apk LAN_IP=<ip>"; exit 1; }; \
	read -r ver commit code <<< "$$(app/tool/version.sh)" || exit 1; \
	echo "La app apuntará a http://$$ip:8000 — versión $$ver ($$commit)"; \
	cd app && flutter build apk --debug --target-platform android-arm64 \
		--build-name=$$ver --build-number=$$code \
		--dart-define=API_URL=http://$$ip:8000 --dart-define=APP_VERSION=$$ver \
		$(if $(API_TIMEOUT_S),--dart-define=API_TIMEOUT_S=$(API_TIMEOUT_S)) \
		--dart-define=APP_COMMIT=$$commit --dart-define=APP_BUILT_AT=$$(date +%Y-%m-%dT%H:%M) \
	&& echo "APK v$$ver: app/build/app/outputs/flutter-apk/app-debug.apk"
