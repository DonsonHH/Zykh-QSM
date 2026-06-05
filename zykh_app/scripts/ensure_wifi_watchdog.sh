#!/bin/sh

set -u

APP_DIR="${ZYKH_APP_DIR:-/userdata/zykh_app}"
PIDFILE="$APP_DIR/data/wifi-watchdog.pid"
OUT="$APP_DIR/data/wifi-watchdog.out"
SCRIPT="$APP_DIR/scripts/start_wifi_watchdog.sh"

mkdir -p "$APP_DIR/data"

if [ -s "$PIDFILE" ]; then
  PID=$(cat "$PIDFILE")
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    echo "Wi-Fi watchdog already running: $PID"
    exit 0
  fi
fi

if command -v setsid >/dev/null 2>&1; then
  setsid sh "$SCRIPT" >> "$OUT" 2>&1 &
  PID=$!
else
  nohup sh "$SCRIPT" >> "$OUT" 2>&1 &
  PID=$!
fi
echo "$PID" > "$PIDFILE"
echo "Wi-Fi watchdog started: $PID"
