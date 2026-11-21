# Imagen del backend. La MISMA imagen sirve para desarrollo (docker compose) y producción
# (Fly.io): lo único que cambia es la configuración, que entra por variables de entorno.
# Guía: docs/06-deploy.md, §«Docker en producción».
FROM python:3.12-slim

# Versión que se muestra en /docs y /v1/health: `make deploy-api` la pasa con --build-arg.
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /srv
COPY pyproject.toml ./
COPY app ./app
RUN pip install .

# No correr como root: si alguien explota una falla de la app, no es dueño del contenedor.
RUN useradd --system --uid 10001 --no-create-home almacenero
USER almacenero

EXPOSE 8000

# Healthcheck de Docker (Fly usa el suyo, el de fly.toml). Solo la librería estándar:
# la imagen slim no trae curl. /v1/health consulta la base: si falla, el contenedor
# se marca «unhealthy».
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/v1/health' % os.environ['PORT'], timeout=8)"]

# Sin --reload (eso es solo para desarrollar). `sh -c` + `exec` para expandir $PORT
# (Fly y otras plataformas eligen el puerto) y que uvicorn reciba las señales de apagado.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
