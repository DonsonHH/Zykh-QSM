#!/bin/sh
set -eu

ROOT="${QSM_LOCAL_ASR_ROOT:-/userdata/zykh_app/local_asr}"
BIN="$ROOT/bin/sherpa-onnx-online-websocket-server"
LIB="$ROOT/lib"
MODEL_DIR="$ROOT/model"
CTC_MODEL="$MODEL_DIR/model.int8.onnx"
ENCODER="$MODEL_DIR/encoder.int8.onnx"
DECODER="$MODEL_DIR/decoder.onnx"
JOINER="$MODEL_DIR/joiner.int8.onnx"
TOKENS="$MODEL_DIR/tokens.txt"
HOTWORDS="${QSM_LOCAL_ASR_HOTWORDS:-$MODEL_DIR/hotwords.txt}"
PORT="${QSM_LOCAL_ASR_PORT:-8084}"
THREADS="${QSM_LOCAL_ASR_THREADS:-2}"
MAX_ACTIVE_PATHS="${QSM_LOCAL_ASR_MAX_ACTIVE_PATHS:-4}"
PID_FILE="${QSM_LOCAL_ASR_PID_FILE:-/userdata/zykh_app/data/local-asr.pid}"
LOG_FILE="${QSM_LOCAL_ASR_LOG_FILE:-/userdata/zykh_app/data/local-asr.log}"

for file in "$BIN" "$LIB/libonnxruntime.so" "$LIB/libsherpa-onnx-c-api.so" "$TOKENS"; do
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
        if [ "${QSM_LOCAL_ASR_RESTART:-0}" = "1" ]; then
          kill "$pid" 2>/dev/null || true
          count=0
          while kill -0 "$pid" 2>/dev/null && [ "$count" -lt 30 ]; do
            count=$((count + 1))
            sleep 0.1
          done
          kill -9 "$pid" 2>/dev/null || true
          rm -f "$PID_FILE"
        else
          echo "[local-asr] ready pid=$pid port=$PORT"
          exit 0
        fi
      fi
      rm -f "$PID_FILE"
      ;;
  esac
fi

listen_pids="$(fuser "${PORT}/tcp" 2>/dev/null || true)"
if [ -n "$listen_pids" ]; then
  if [ "${QSM_LOCAL_ASR_RESTART:-0}" = "1" ]; then
    for pid in $listen_pids; do
      kill "$pid" 2>/dev/null || true
    done
    sleep 1
    for pid in $listen_pids; do
      kill -9 "$pid" 2>/dev/null || true
    done
  else
    echo "[local-asr] ready pid=$listen_pids port=$PORT"
    exit 0
  fi
fi

export LD_LIBRARY_PATH="$LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
set -- \
  --port="$PORT" \
  --num-work-threads="$THREADS" \
  --num-io-threads=1 \
  --num-threads="$THREADS" \
  --tokens="$TOKENS" \
  --enable-endpoint=true \
  --rule1-min-trailing-silence=2.4 \
  --rule2-min-trailing-silence=1.1 \
  --rule3-min-utterance-length=20 \
  --log-file="$LOG_FILE"

if [ -s "$ENCODER" ] && [ -s "$DECODER" ] && [ -s "$JOINER" ]; then
  set -- "$@" \
    --encoder="$ENCODER" \
    --decoder="$DECODER" \
    --joiner="$JOINER" \
    --model-type=zipformer2 \
    --decoding-method=modified_beam_search \
    --max-active-paths="$MAX_ACTIVE_PATHS"
  if [ -s "$HOTWORDS" ]; then
    set -- "$@" \
      --hotwords-file="$HOTWORDS" \
      --hotwords-score=1.5 \
      --modeling-unit=cjkchar
  fi
  MODEL_NAME="sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
elif [ -s "$CTC_MODEL" ]; then
  set -- "$@" \
    --zipformer2-ctc-model="$CTC_MODEL" \
    --model-type=zipformer2
  MODEL_NAME="sherpa-onnx-streaming-zipformer-small-ctc-zh-int8-2025-04-01"
else
  echo "[local-asr] no supported model found in $MODEL_DIR" >&2
  exit 2
fi

printf '%s\n' "$MODEL_NAME" > "$ROOT/model-name.txt"
start-stop-daemon -S -b -m -p "$PID_FILE" -x "$BIN" -- "$@"

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
