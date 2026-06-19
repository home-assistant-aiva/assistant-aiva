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

if [ "$#" -eq 0 ]; then
  ZIP_PATH="$(find dist -maxdepth 1 -type f -name 'aiva-collector-windows-manual-v*.zip' -printf '%T@ %p\n' | sort -n | tail -1 | awk '{print $2}')"
  if [ -z "${ZIP_PATH:-}" ]; then
    echo "No se encontro ZIP en dist/." >&2
    exit 1
  fi
  set -- --zip "$ZIP_PATH"
fi

"$PYTHON_BIN" scripts/test_clean_windows_package_install.py "$@"
