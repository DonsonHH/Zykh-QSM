#!/usr/bin/env sh
set -eu

LOCAL_PORT="${QSM_ADB_LOCAL_PORT:-18080}"
REMOTE_PORT="${QSM_ADB_REMOTE_PORT:-8080}"
QSM_BASE="${QSM_API_BASE:-http://127.0.0.1:${LOCAL_PORT}}"

echo "[adb] devices"
adb devices -l

echo "[adb] forward tcp:${LOCAL_PORT} tcp:${REMOTE_PORT}"
adb forward "tcp:${LOCAL_PORT}" "tcp:${REMOTE_PORT}"

echo "[qsm] ${QSM_BASE}/api/status"
if command -v curl >/dev/null 2>&1; then
  curl -fsS "${QSM_BASE}/api/status" || true
  echo
fi
