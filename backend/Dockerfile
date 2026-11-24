# El contexto de build es la RAÍZ del repo (docker-compose.yml): la imagen lleva `etl/` junto a
# `app/` porque el panel dispara ETL livianos como subproceso del backend (docs/04 §10-A).
# Sin los extras pesados (`pyosmium`): los ETL pesados corren en el worker local.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY etl ./etl
RUN pip install .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
