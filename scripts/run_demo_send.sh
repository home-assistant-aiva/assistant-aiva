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

if [ -z "${AIVA_COLLECTOR_TOKEN:-}" ]; then
  echo "Falta AIVA_COLLECTOR_TOKEN. No se imprime ni se guarda el token." >&2
  exit 2
fi

if [ -z "${AIVA_COLLECTOR_COMMERCE_ID:-}" ] || [ -z "${AIVA_COLLECTOR_ID:-}" ]; then
  echo "Definir AIVA_COLLECTOR_COMMERCE_ID y AIVA_COLLECTOR_ID, o ajustar config.local.json con IDs reales." >&2
  exit 2
fi

if [ ! -f config.local.json ]; then
  "$PYTHON_BIN" -m aiva_collector.cli init-config --output config.local.json
  "$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path
path = Path("config.local.json")
data = json.loads(path.read_text(encoding="utf-8"))
import os
data["commerce_id"] = os.environ["AIVA_COLLECTOR_COMMERCE_ID"]
data["collector_id"] = os.environ["AIVA_COLLECTOR_ID"]
path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")
PY
fi

echo "ADVERTENCIA: se enviara un summary al backend configurado. No se imprimira el token."
"$PYTHON_BIN" -m aiva_collector.cli run-once --config config.local.json --send
