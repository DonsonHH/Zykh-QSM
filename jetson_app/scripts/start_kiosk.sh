#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
APP_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"

if [ -f "${APP_ROOT}/.env" ]; then
  set -a
  . "${APP_ROOT}/.env"
  set +a
fi

HOST="${JETSON_HOST:-127.0.0.1}"
PORT="${JETSON_PORT:-8088}"
URL="http://${HOST}:${PORT}/"
LOG_DIR="${APP_ROOT}/data"
PROFILE_DIR="${CHROMIUM_PROFILE_DIR:-${LOG_DIR}/chromium-profile}"
mkdir -p "${LOG_DIR}"
mkdir -p "${PROFILE_DIR}"

if command -v curl >/dev/null 2>&1; then
  if ! curl -fsS "${URL}api/status" >/dev/null 2>&1; then
    echo "[jetson] backend is not responding, starting it"
    nohup "${SCRIPT_DIR}/start_jetson_app.sh" > "${LOG_DIR}/backend.log" 2>&1 &
    i=0
    until curl -fsS "${URL}api/status" >/dev/null 2>&1; do
      i=$((i + 1))
      [ "$i" -ge 20 ] && break
      sleep 1
    done
  fi
fi

CHROMIUM_BIN="${CHROMIUM_BIN:-}"
if [ -z "${CHROMIUM_BIN}" ]; then
  CHROMIUM_BIN="$(command -v chromium || command -v chromium-browser || command -v google-chrome || true)"
fi

if [ -z "${CHROMIUM_BIN}" ]; then
  echo "Chromium not found. Set CHROMIUM_BIN or install Chromium." >&2
  exit 1
fi

exec "${CHROMIUM_BIN}" \
  --kiosk \
  --app="${URL}" \
  --window-size=1280,720 \
  --force-device-scale-factor=1 \
  --disable-gpu \
  --disable-translate \
  --no-first-run \
  --disable-session-crashed-bubble \
  --disable-infobars \
  --user-data-dir="${PROFILE_DIR}"
