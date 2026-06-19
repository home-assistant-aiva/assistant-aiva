#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

BUILD_OUTPUT="$("$PYTHON_BIN" scripts/build_windows_package.py)"
echo "$BUILD_OUTPUT"

ZIP_PATH="$(printf '%s\n' "$BUILD_OUTPUT" | awk -F'ZIP: ' '/^ZIP: / {print $2}')"
if [ -z "$ZIP_PATH" ]; then
  echo "No se pudo detectar la ruta del ZIP generado." >&2
  exit 1
fi

"$PYTHON_BIN" scripts/verify_windows_package.py "$ZIP_PATH"

SHA256="$(sha256sum "$ZIP_PATH" | awk '{print $1}')"
echo "Paquete Windows listo: $ZIP_PATH"
echo "SHA256: $SHA256"
