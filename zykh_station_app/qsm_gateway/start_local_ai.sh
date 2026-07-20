#!/bin/sh

set -u

RUNTIME_DIR="${LOCAL_AI_RUNTIME_DIR:-/userdata/zykh_station_app/local-ai}"
ASSET_DIR="${LOCAL_AI_ASSET_DIR:-/opt/zykh-local-ai}"
SERVER="${LOCAL_AI_SERVER:-$ASSET_DIR/llama-server}"
MODEL="${LOCAL_AI_MODEL_FILE:-$ASSET_DIR/models/Qwen3.5-0.8B-Q4_K_M.gguf}"
HOST="${LOCAL_AI_HOST:-0.0.0.0}"
PORT="${LOCAL_AI_PORT:-8083}"
CTX_SIZE="${LOCAL_AI_CTX_SIZE:-1024}"
THREADS="${LOCAL_AI_THREADS:-3}"
BATCH_SIZE="${LOCAL_AI_BATCH_SIZE:-128}"
UBATCH_SIZE="${LOCAL_AI_UBATCH_SIZE:-32}"
PID_FILE="$RUNTIME_DIR/llama-server.pid"
LOG_FILE="$RUNTIME_DIR/llama-server.log"
START_TIMEOUT="${LOCAL_AI_START_TIMEOUT:-65}"

mkdir -p "$RUNTIME_DIR"

health_ready() {
  wget -qO- "http://127.0.0.1:$PORT/health" 2>/dev/null \
    | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"'
}

if health_ready; then
  echo "Local AI already ready on port $PORT"
  exit 0
fi

if [ ! -x "$SERVER" ]; then
  echo "Local AI engine not found: $SERVER" >&2
  exit 1
fi
if [ ! -s "$MODEL" ]; then
  echo "Local AI model not found: $MODEL" >&2
  exit 1
fi

if [ -s "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  case "$OLD_PID" in
    ''|*[!0-9]*) rm -f "$PID_FILE" ;;
    *)
      if kill -0 "$OLD_PID" 2>/dev/null; then
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
      fi
      rm -f "$PID_FILE"
      ;;
  esac
fi

: >"$LOG_FILE"
if command -v setsid >/dev/null 2>&1; then
  nohup setsid "$SERVER" \
    -m "$MODEL" \
    --host "$HOST" \
    --port "$PORT" \
    --ctx-size "$CTX_SIZE" \
    --threads "$THREADS" \
    --threads-batch "$THREADS" \
    --batch-size "$BATCH_SIZE" \
    --ubatch-size "$UBATCH_SIZE" \
    --parallel 1 \
    --reasoning off \
    --reasoning-budget 0 \
    --no-warmup \
    >"$LOG_FILE" 2>&1 </dev/null &
else
  nohup "$SERVER" \
    -m "$MODEL" \
    --host "$HOST" \
    --port "$PORT" \
    --ctx-size "$CTX_SIZE" \
    --threads "$THREADS" \
    --threads-batch "$THREADS" \
    --batch-size "$BATCH_SIZE" \
    --ubatch-size "$UBATCH_SIZE" \
    --parallel 1 \
    --reasoning off \
    --reasoning-budget 0 \
    --no-warmup \
    >"$LOG_FILE" 2>&1 </dev/null &
fi
PID="$!"
echo "$PID" >"$PID_FILE"

WAITED=0
while [ "$WAITED" -lt "$START_TIMEOUT" ]; do
  if health_ready; then
    echo "Local AI ready: PID $PID, port $PORT"
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "Local AI exited during startup" >&2
    tail -80 "$LOG_FILE" >&2
    rm -f "$PID_FILE"
    exit 1
  fi
  WAITED=$((WAITED + 1))
  sleep 1
done

echo "Local AI startup timed out after ${START_TIMEOUT}s" >&2
tail -80 "$LOG_FILE" >&2
exit 1
