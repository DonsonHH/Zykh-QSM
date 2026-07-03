#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR/backend"

PYTHON_BIN="${PYTHON_BIN:-python}"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
fi

exec "$PYTHON_BIN" -m uvicorn app.main:app --host "${ZYKH_STATION_HOST:-127.0.0.1}" --port "${ZYKH_STATION_PORT:-8000}"
