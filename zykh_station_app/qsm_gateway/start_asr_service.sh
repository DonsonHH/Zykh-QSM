#!/bin/sh
set -eu

ACTION="${1:-start}"
VOICE_ROOT="${ZYKH_VOICE_ROOT:-/userdata/zykh_voice}"
BIN="$VOICE_ROOT/runtime/bin/sherpa-onnx-offline-websocket-server"
MODEL_DIR="$VOICE_ROOT/models/asr-paraformer"
RUN_DIR="${ASR_RUN_DIR:-/userdata/zykh_app/data/asr-service}"
PID_FILE="$RUN_DIR/asr-service.pid"
LOG_FILE="$RUN_DIR/asr-service.log"
ENGINE_LOG="$RUN_DIR/sherpa-engine.log"
PORT="${ASR_WS_PORT:-6006}"

mkdir -p "$RUN_DIR"

is_running() {
  [ -s "$PID_FILE" ] || return 1
  kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

is_listening() {
  netstat -ltn 2>/dev/null | grep -q ":$PORT "
}

stop_service() {
  if is_running; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$PID_FILE"
}

if [ "$ACTION" = "stop" ]; then
  stop_service
  echo "offline ASR service stopped"
  exit 0
fi

if [ "$ACTION" = "status" ]; then
  if is_running && is_listening; then
    echo "offline ASR service is ready on 127.0.0.1:$PORT"
    exit 0
  fi
  echo "offline ASR service is not ready"
  exit 1
fi

for file in "$BIN" "$MODEL_DIR/model.int8.onnx" "$MODEL_DIR/tokens.txt"; do
  [ -s "$file" ] || { echo "missing ASR file: $file" >&2; exit 3; }
done

if is_running && is_listening; then
  echo "offline ASR service already ready on 127.0.0.1:$PORT"
  exit 0
fi
stop_service

export LD_LIBRARY_PATH="$VOICE_ROOT/runtime/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export OMP_NUM_THREADS="${ASR_THREADS:-2}"

nohup "$BIN" \
  --port="$PORT" \
  --model-type=paraformer \
  --tokens="$MODEL_DIR/tokens.txt" \
  --paraformer="$MODEL_DIR/model.int8.onnx" \
  --num-threads="${ASR_THREADS:-2}" \
  --num-work-threads="${ASR_WORK_THREADS:-1}" \
  --num-io-threads=1 \
  --max-batch-size=1 \
  --max-utterance-length="${ASR_MAX_UTTERANCE_SECONDS:-20}" \
  --log-file="$ENGINE_LOG" \
  >"$LOG_FILE" 2>&1 </dev/null &
echo $! > "$PID_FILE"

WAIT_SECONDS="${ASR_START_TIMEOUT:-30}"
i=0
while [ "$i" -lt "$WAIT_SECONDS" ]; do
  if is_running && is_listening; then
    echo "offline ASR service ready: pid=$(cat "$PID_FILE"), port=$PORT"
    exit 0
  fi
  sleep 1
  i=$((i + 1))
done

echo "offline ASR service failed to start; log follows" >&2
tail -80 "$LOG_FILE" >&2 2>/dev/null || true
exit 4
