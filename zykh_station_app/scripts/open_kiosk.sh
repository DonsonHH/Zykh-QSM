#!/usr/bin/env sh
set -eu

APP_URL="${1:-http://127.0.0.1:5173}"
KIOSK_WIDTH="${KIOSK_WIDTH:-1280}"
KIOSK_HEIGHT="${KIOSK_HEIGHT:-720}"
KIOSK_OUTPUT="${KIOSK_OUTPUT:-}"
KIOSK_SCALE="${KIOSK_SCALE:-1}"

if [ "${KIOSK_SKIP_RESOLUTION:-0}" != "1" ] && command -v xrandr >/dev/null 2>&1; then
  OUTPUT="$KIOSK_OUTPUT"
  if [ -z "$OUTPUT" ]; then
    OUTPUT="$(xrandr --query | awk '/ connected/{print $1; exit}')"
  fi
  if [ -n "$OUTPUT" ]; then
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

exec "$BROWSER" \
  --kiosk "$APP_URL" \
  --start-fullscreen \
  --window-position=0,0 \
  --window-size="${KIOSK_WIDTH},${KIOSK_HEIGHT}" \
  --force-device-scale-factor="$KIOSK_SCALE" \
  --disable-pinch \
  --overscroll-history-navigation=0
