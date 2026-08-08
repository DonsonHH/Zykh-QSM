#!/bin/sh

set -u

RUNTIME_DIR="${LOCAL_AI_RUNTIME_DIR:-/userdata/zykh_station_app/local-ai}"
ASSET_DIR="${LOCAL_AI_ASSET_DIR:-/opt/zykh-local-ai}"
SERVER="${LOCAL_AI_SERVER:-$ASSET_DIR/llama-server}"
MODEL="${LOCAL_AI_MODEL_FILE:-$ASSET_DIR/models/Qwen3.5-0.8B-Q4_K_M.gguf}"
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

if ! kill -0 "$PID" 2>/dev/null; then
  rm -f "$PID_FILE"
  echo "Local AI is not running"
  exit 0
fi

CMDLINE="$(tr '\000' ' ' <"/proc/$PID/cmdline" 2>/dev/null || true)"
case "$CMDLINE" in
  *"$SERVER"*"$MODEL"*) ;;
  *)
    echo "Refusing to stop PID $PID because it is not the managed Local AI process" >&2
    exit 1
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
