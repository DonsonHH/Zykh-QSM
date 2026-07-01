#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
APP_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
TARGET_MODE="${JETSON_KIOSK_MODE:-1280x720}"
TARGET_RATE="${JETSON_KIOSK_RATE:-60}"
OUTPUT="${JETSON_KIOSK_OUTPUT:-}"
PREV_MODE=""

if [ -f "${APP_ROOT}/.env" ]; then
  set -a
  . "${APP_ROOT}/.env"
  set +a
fi

pick_output() {
  xrandr --query | awk '/ connected/{print $1; exit}'
}

current_mode() {
  xrandr --query | awk -v out="$1" '
    $1 == out && $2 == "connected" { active = 1; next }
    /^[^ ]/ { active = 0 }
    active && /\*/ { print $1; exit }
  '
}

mode_exists() {
  xrandr --query | awk -v out="$1" -v mode="$2" '
    $1 == out && $2 == "connected" { active = 1; next }
    /^[^ ]/ { active = 0 }
    active && $1 == mode { found = 1 }
    END { exit found ? 0 : 1 }
  '
}

restore_resolution() {
  if [ -n "${OUTPUT}" ] && [ -n "${PREV_MODE}" ] && command -v xrandr >/dev/null 2>&1; then
    xrandr --output "${OUTPUT}" --mode "${PREV_MODE}" >/dev/null 2>&1 || true
    echo "[kiosk] restored ${OUTPUT} to ${PREV_MODE}"
  fi
}

trap restore_resolution EXIT INT TERM

if command -v xrandr >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ]; then
  if [ -z "${OUTPUT}" ]; then
    OUTPUT="$(pick_output || true)"
  fi

  if [ -n "${OUTPUT}" ]; then
    PREV_MODE="$(current_mode "${OUTPUT}" || true)"
    if mode_exists "${OUTPUT}" "${TARGET_MODE}"; then
      echo "[kiosk] setting ${OUTPUT} to ${TARGET_MODE}@${TARGET_RATE}"
      xrandr --output "${OUTPUT}" --mode "${TARGET_MODE}" --rate "${TARGET_RATE}" || xrandr --output "${OUTPUT}" --mode "${TARGET_MODE}"
    else
      echo "[kiosk] ${TARGET_MODE} is not listed for ${OUTPUT}; keeping current display mode" >&2
    fi
  else
    echo "[kiosk] no connected xrandr output found; keeping current display mode" >&2
  fi
else
  echo "[kiosk] xrandr or DISPLAY unavailable; keeping current display mode" >&2
fi

"${SCRIPT_DIR}/start_kiosk.sh"
