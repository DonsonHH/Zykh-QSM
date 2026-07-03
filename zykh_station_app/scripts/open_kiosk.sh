#!/usr/bin/env sh
set -eu

APP_URL="${1:-http://127.0.0.1:5173}"

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
  --window-size=1280,720 \
  --force-device-scale-factor=1 \
  --disable-pinch \
  --overscroll-history-navigation=0
