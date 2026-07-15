#!/bin/sh
set -eu

ROOT="${QSM_LOCAL_ASR_ROOT:-/userdata/zykh_app/local_asr}"
BIN="$ROOT/bin/sherpa-onnx-online-websocket-server"
LIB="$ROOT/lib"
MODEL="$ROOT/model/model.int8.onnx"
TOKENS="$ROOT/model/tokens.txt"
PORT="${QSM_LOCAL_ASR_PORT:-8084}"
THREADS="${QSM_LOCAL_ASR_THREADS:-2}"
PID_FILE="${QSM_LOCAL_ASR_PID_FILE:-/userdata/zykh_app/data/local-asr.pid}"
LOG_FILE="${QSM_LOCAL_ASR_LOG_FILE:-/userdata/zykh_app/data/local-asr.log}"

for file in "$BIN" "$LIB/libonnxruntime.so" "$LIB/libsherpa-onnx-c-api.so" "$MODEL" "$TOKENS"; do
  if [ ! -s "$file" ]; then
    echo "[local-asr] missing: $file" >&2
    exit 2
  fi
done

mkdir -p "$(dirname "$PID_FILE")"
if [ -s "$PID_FILE" ]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  case "$pid" in
    ''|*[!0-9]*) rm -f "$PID_FILE" ;;
    *)
      if kill -0 "$pid" 2>/dev/null; then
        echo "[local-asr] ready pid=$pid port=$PORT"
        exit 0
      fi
      rm -f "$PID_FILE"
      ;;
  esac
fi

export LD_LIBRARY_PATH="$LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
start-stop-daemon -S -b -m -p "$PID_FILE" -x "$BIN" -- \
  --port="$PORT" \
  --num-work-threads="$THREADS" \
  --num-io-threads=1 \
  --num-threads="$THREADS" \
  --tokens="$TOKENS" \
  --zipformer2-ctc-model="$MODEL" \
  --model-type=zipformer2 \
  --enable-endpoint=true \
  --rule1-min-trailing-silence=1.2 \
  --rule2-min-trailing-silence=0.7 \
  --rule3-min-utterance-length=12 \
  --log-file="$LOG_FILE"

count=0
while [ "$count" -lt 100 ]; do
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if netstat -lnt 2>/dev/null | grep -Eq "[:.]${PORT}[[:space:]]"; then
    echo "[local-asr] started pid=$(cat "$PID_FILE") port=$PORT"
    exit 0
  fi
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    echo "[local-asr] process exited before port $PORT became ready" >&2
    tail -20 "$LOG_FILE" 2>/dev/null >&2 || true
    exit 3
  fi
  count=$((count + 1))
  sleep 0.2
done

echo "[local-asr] process started but port $PORT is not ready" >&2
exit 3
