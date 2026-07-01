#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
APP_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${APP_ROOT}/backend"
DATA_DIR="${JETSON_DATA_DIR:-${APP_ROOT}/data}"
DB_PATH="${JETSON_DB_PATH:-${DATA_DIR}/zykh_jetson.db}"
BACKUP_DIR="${DATA_DIR}/backups"
PYTHON="${PYTHON:-python3}"

if [ -f "${APP_ROOT}/.env" ]; then
  set -a
  . "${APP_ROOT}/.env"
  set +a
fi

if [ -x "${BACKEND_DIR}/.venv/bin/python" ]; then
  PYTHON="${BACKEND_DIR}/.venv/bin/python"
fi

mkdir -p "${BACKUP_DIR}"

if [ -f "${DB_PATH}" ]; then
  stamp="$(date +%Y%m%d-%H%M%S)"
  cp "${DB_PATH}" "${BACKUP_DIR}/zykh_jetson.before-demo-${stamp}.db"
  echo "[demo] backed up ${DB_PATH}"
fi

cd "${BACKEND_DIR}"
export PYTHONPATH="${BACKEND_DIR}:${PYTHONPATH:-}"
"${PYTHON}" -m app.demo_data
echo "[demo] seeded Jetson demo profile, medicines, plans, vitals and records"
