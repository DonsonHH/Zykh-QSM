#!/usr/bin/env sh
set -eu

APP_URL="${1:-http://127.0.0.1:5173}"
KIOSK_WIDTH="${KIOSK_WIDTH:-1280}"
KIOSK_HEIGHT="${KIOSK_HEIGHT:-720}"
KIOSK_OUTPUT="${KIOSK_OUTPUT:-}"
KIOSK_SCALE="${KIOSK_SCALE:-1}"
KIOSK_SAFE_GRAPHICS="${KIOSK_SAFE_GRAPHICS:-1}"
KIOSK_RESTORE_RESOLUTION="${KIOSK_RESTORE_RESOLUTION:-1}"
KIOSK_BROWSER_LOG="${KIOSK_BROWSER_LOG:-file}"
ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
RUN_DIR="$ROOT_DIR/data/run"
BROWSER_PID=""
RESTORE_OUTPUT=""
RESTORE_MODE=""

mkdir -p "$RUN_DIR"

log() {
  printf '[kiosk] %s\n' "$*"
}

warn() {
  printf '[kiosk] WARN: %s\n' "$*" >&2
}

start_browser() {
  if [ "$KIOSK_BROWSER_LOG" = "terminal" ]; then
    "$@" &
  else
    log "浏览器日志：$RUN_DIR/chromium.log"
    "$@" >"$RUN_DIR/chromium.log" 2>&1 &
  fi
  BROWSER_PID="$!"
}

current_mode_for_output() {
  xrandr --query | awk -v output="$1" '
    $1 == output && $2 == "connected" { found = 1; next }
    found && /^[[:space:]]/ && /\*/ { print $1; exit }
    found && /^[^[:space:]]/ { found = 0 }
  '
}

restore_resolution() {
  if [ "$KIOSK_RESTORE_RESOLUTION" != "1" ]; then
    return 0
  fi
  if [ -z "$RESTORE_OUTPUT" ] || [ -z "$RESTORE_MODE" ]; then
    return 0
  fi
  if ! command -v xrandr >/dev/null 2>&1; then
    return 0
  fi
  if xrandr --output "$RESTORE_OUTPUT" --mode "$RESTORE_MODE" >/dev/null 2>&1; then
    log "显示输出 $RESTORE_OUTPUT 已恢复到 $RESTORE_MODE。"
  else
    warn "无法恢复显示输出 $RESTORE_OUTPUT 到 $RESTORE_MODE。"
  fi
}

stop_browser() {
  if [ -n "$BROWSER_PID" ] && kill -0 "$BROWSER_PID" >/dev/null 2>&1; then
    kill "$BROWSER_PID" >/dev/null 2>&1 || true
    wait "$BROWSER_PID" 2>/dev/null || true
  fi
}

on_exit() {
  status="$?"
  trap - EXIT INT TERM
  stop_browser
  restore_resolution
  exit "$status"
}

on_signal() {
  trap - EXIT INT TERM
  stop_browser
  restore_resolution
  exit 130
}

trap on_exit EXIT
trap on_signal INT TERM

if [ "${KIOSK_SKIP_RESOLUTION:-0}" != "1" ] && command -v xrandr >/dev/null 2>&1; then
  OUTPUT="$KIOSK_OUTPUT"
  if [ -z "$OUTPUT" ]; then
    OUTPUT="$(xrandr --query | awk '/ connected/{print $1; exit}')"
  fi
  if [ -n "$OUTPUT" ]; then
    RESTORE_OUTPUT="$OUTPUT"
    RESTORE_MODE="$(current_mode_for_output "$OUTPUT" || true)"
    xrandr --output "$OUTPUT" --mode "${KIOSK_WIDTH}x${KIOSK_HEIGHT}" >/dev/null 2>&1 || \
      xrandr --size "${KIOSK_WIDTH}x${KIOSK_HEIGHT}" >/dev/null 2>&1 || true
  fi
fi

if command -v chromium >/dev/null 2>&1; then
  BROWSER="chromium"
elif command -v chromium-browser >/dev/null 2>&1; then
  BROWSER="chromium-browser"
elif command -v google-chrome >/dev/null 2>&1; then
  BROWSER="google-chrome"
else
  echo "未找到 Chromium/Chrome 浏览器，请先安装后再运行。" >&2
  exit 1
fi

set -- "$BROWSER" \
  --kiosk "$APP_URL" \
  --start-fullscreen \
  --window-position=0,0 \
  --window-size="${KIOSK_WIDTH},${KIOSK_HEIGHT}" \
  --force-device-scale-factor="$KIOSK_SCALE" \
  --disable-pinch \
  --overscroll-history-navigation=0

if [ "$KIOSK_SAFE_GRAPHICS" = "1" ]; then
  set -- "$@" \
    --ozone-platform=x11 \
    --disable-gpu \
    --disable-accelerated-2d-canvas \
    --disable-background-networking \
    --disable-component-update \
    --disable-default-apps \
    --disable-extensions \
    --disable-sync \
    --metrics-recording-only \
    --disable-features=Vulkan,OptimizationGuideOnDeviceModel \
    --disable-dev-shm-usage
fi

start_browser "$@"
wait "$BROWSER_PID"
BROWSER_PID=""
