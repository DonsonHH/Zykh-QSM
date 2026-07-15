#!/bin/sh

set -u

RUNTIME_DIR="${LOCAL_AI_RUNTIME_DIR:-/userdata/zykh_station_app/local-ai}"
PID_FILE="$RUNTIME_DIR/llama-server.pid"

if [ ! -s "$PID_FILE" ]; then
  echo "Local AI is not running"
  exit 0
fi

PID="$(cat "$PID_FILE" 2>/dev/null || true)"
case "$PID" in
  ''|*[!0-9]*)
    rm -f "$PID_FILE"
    echo "Local AI PID file was invalid"
    exit 0
    ;;
esac

kill "$PID" 2>/dev/null || true
WAITED=0
while kill -0 "$PID" 2>/dev/null && [ "$WAITED" -lt 12 ]; do
  WAITED=$((WAITED + 1))
  sleep 1
done
kill -9 "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
echo "Local AI stopped"
