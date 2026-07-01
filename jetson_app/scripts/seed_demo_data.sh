#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
APP_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${APP_ROOT}/backend"
PYTHON="${PYTHON:-python3}"

if [ -f "${APP_ROOT}/.env" ]; then
  set -a
  . "${APP_ROOT}/.env"
  set +a
fi

DATA_DIR="${QSM_DATA_DIR:-${JETSON_DATA_DIR:-${APP_ROOT}/data}}"
if [ -n "${QSM_DB_PATH:-}" ]; then
  DB_PATH="${QSM_DB_PATH}"
elif [ -n "${JETSON_DB_PATH:-}" ]; then
  DB_PATH="${JETSON_DB_PATH}"
elif [ -f "${DATA_DIR}/zykh_jetson.db" ]; then
  DB_PATH="${DATA_DIR}/zykh_jetson.db"
else
  DB_PATH="${DATA_DIR}/zykh_qsm.db"
fi
BACKUP_DIR="${DATA_DIR}/backups"

if [ -x "${BACKEND_DIR}/.venv/bin/python" ]; then
  PYTHON="${BACKEND_DIR}/.venv/bin/python"
fi

mkdir -p "${BACKUP_DIR}"

if [ -f "${DB_PATH}" ]; then
  stamp="$(date +%Y%m%d-%H%M%S)"
  db_name="${DB_PATH##*/}"
  db_name="${db_name%.db}"
  cp "${DB_PATH}" "${BACKUP_DIR}/${db_name}.before-demo-${stamp}.db"
  echo "[demo] backed up ${DB_PATH}"
fi

cd "${BACKEND_DIR}"
export PYTHONPATH="${BACKEND_DIR}:${PYTHONPATH:-}"
"${PYTHON}" -m app.demo_data
echo "[demo] seeded QSM demo profile, medicines, plans, vitals and records"
