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

if [ ! -f config.local.json ]; then
  "$PYTHON_BIN" -m aiva_collector.cli init-config --output config.local.json
fi

"$PYTHON_BIN" -m aiva_collector.cli validate --config config.local.json
"$PYTHON_BIN" -m aiva_collector.cli run-once --config config.local.json

echo "last_summary.json: $(pwd)/samples/output/last_summary.json"
