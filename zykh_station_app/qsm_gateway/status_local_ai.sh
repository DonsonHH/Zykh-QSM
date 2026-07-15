#!/bin/sh

set -u

RUNTIME_DIR="${LOCAL_AI_RUNTIME_DIR:-/userdata/zykh_station_app/local-ai}"
ASSET_DIR="${LOCAL_AI_ASSET_DIR:-/opt/zykh-local-ai}"
MODEL="${LOCAL_AI_MODEL_FILE:-$ASSET_DIR/models/Qwen3.5-0.8B-Q4_K_M.gguf}"
PORT="${LOCAL_AI_PORT:-8083}"
PID_FILE="$RUNTIME_DIR/llama-server.pid"
PID=""
RUNNING=false
READY=false

if [ -s "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  case "$PID" in
    ''|*[!0-9]*) PID="" ;;
    *) kill -0 "$PID" 2>/dev/null && RUNNING=true ;;
  esac
fi
if wget -qO- "http://127.0.0.1:$PORT/health" 2>/dev/null \
  | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"'; then
  READY=true
fi

MODEL_PRESENT=false
[ -s "$MODEL" ] && MODEL_PRESENT=true

printf '{"ok":%s,"running":%s,"ready":%s,"pid":"%s","port":%s,"model_present":%s,"model":"%s"}\n' \
  "$READY" "$RUNNING" "$READY" "$PID" "$PORT" "$MODEL_PRESENT" "$(basename "$MODEL")"

[ "$READY" = true ]
