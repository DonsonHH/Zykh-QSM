#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
APP_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${APP_ROOT}/backend"

if [ -f "${APP_ROOT}/.env" ]; then
  set -a
  . "${APP_ROOT}/.env"
  set +a
fi

HOST="${QSM_HOST:-127.0.0.1}"
PORT="${QSM_PORT:-8088}"
PYTHON="${PYTHON:-python3}"

if [ -x "${BACKEND_DIR}/.venv/bin/python" ]; then
  PYTHON="${BACKEND_DIR}/.venv/bin/python"
fi

cd "${BACKEND_DIR}"
export PYTHONPATH="${BACKEND_DIR}:${PYTHONPATH:-}"
exec "${PYTHON}" -m uvicorn app.main:app --host "${HOST}" --port "${PORT}"
