#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
APP_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"

if [ -f "${APP_ROOT}/.env" ]; then
  set -a
  . "${APP_ROOT}/.env"
  set +a
fi

HOST="${QSM_HOST:-127.0.0.1}"
PORT="${QSM_PORT:-8088}"
LOCAL_PORT="${QSM_ADB_LOCAL_PORT:-18080}"

check_cmd() {
  name="$1"
  cmd="$2"
  if command -v "$cmd" >/dev/null 2>&1; then
    printf '[ok] %s: %s\n' "$name" "$(command -v "$cmd")"
  else
    printf '[missing] %s\n' "$name"
  fi
}

check_cmd python3 python3
check_cmd node node
check_cmd npm npm
check_cmd adb adb
check_cmd curl curl
check_cmd chromium chromium

echo "[adb] devices"
if command -v adb >/dev/null 2>&1; then
  adb devices -l || true
fi

echo "[qsm-main] http://${HOST}:${PORT}/api/status"
if command -v curl >/dev/null 2>&1; then
  curl -fsS "http://${HOST}:${PORT}/api/status" || true
  echo
fi

echo "[peripheral] http://127.0.0.1:${LOCAL_PORT}/api/status"
if command -v curl >/dev/null 2>&1; then
  curl -fsS "http://127.0.0.1:${LOCAL_PORT}/api/status" || true
  echo
fi
