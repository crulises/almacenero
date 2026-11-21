# Panel de admin: nginx sin privilegios sirviendo archivos estáticos bajo /admin/.
# Guía: docs/06-deploy.md, §«Docker en producción».
FROM nginxinc/nginx-unprivileged:1.27-alpine

# Variable que se inyecta en /admin/config.js al arrancar (ver nginx.conf.template).
# Vacía = el panel usa «mismo host, puerto 8000» (desarrollo local, también desde la LAN).
ENV API_URL=""

# nginx reemplaza ${API_URL} en los *.template al arrancar y deja el resultado en conf.d.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY public /usr/share/nginx/html/admin
# config.js lo genera nginx (la URL del API cambia por entorno): el archivo no se copia.
RUN rm -f /usr/share/nginx/html/admin/config.js

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
