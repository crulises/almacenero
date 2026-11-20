#!/usr/bin/env bash
# Versión del próximo APK. Imprime: "<version> <commit> <build-number>".
#
# - La SERIE (0.0, 0.1, ...) sale de `version:` en pubspec.yaml: la cambia una persona
#   cuando cierra un ciclo de pruebas.
# - El último número sube solo en cada ejecución (cada `make apk`). Al cambiar de serie
#   vuelve a 0 (0.1.0, 0.1.1, ...).
# - El contador vive en el .git COMPARTIDO (no en el árbol de trabajo): no ensucia el
#   repo ni genera conflictos de merge, y todos los worktrees cuentan juntos.
#   (VERSION_COUNTER_FILE lo redirige a otro archivo: sirve para probar el script.)
set -euo pipefail
cd "$(dirname "$0")/.."

serie=$(sed -n 's/^version: *\([0-9][0-9]*\.[0-9][0-9]*\)\..*/\1/p' pubspec.yaml)
[ -n "$serie" ] || { echo "no pude leer la versión de pubspec.yaml" >&2; exit 1; }

contador="${VERSION_COUNTER_FILE:-$(cd "$(git rev-parse --git-common-dir)" && pwd)/almacenero-apk-version}"
serie_previa=""
patch=0
if [ -f "$contador" ]; then read -r serie_previa patch < "$contador"; fi
if [ "$serie_previa" = "$serie" ]; then
  patch=$((patch + 1))
elif [ -z "$serie_previa" ]; then
  patch=1
else
  patch=0
fi
echo "$serie $patch" > "$contador"

commit=$(git rev-parse --short HEAD)
if [ -n "$(git status --porcelain)" ]; then commit="$commit+local"; fi  # cambios sin commitear
# versionCode de Android: tiene que crecer siempre para poder instalar encima.
echo "$serie.$patch $commit $(date +%s)"
