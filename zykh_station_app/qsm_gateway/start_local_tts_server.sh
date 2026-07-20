#!/usr/bin/env sh
set -eu

QSM_HOME="${QSM_HOME:-/userdata/zykh_app}"
VOICE_ROOT="${ZYKH_VOICE_ROOT:-/userdata/zykh_voice}"
BIN="${QSM_LOCAL_TTS_BIN:-$QSM_HOME/bin/local-tts-server}"
PORT="${QSM_LOCAL_TTS_PORT:-19002}"
ACTION="${1:-start}"
PID_FILE="${QSM_LOCAL_TTS_PID_FILE:-$QSM_HOME/data/local-tts.pid}"
LOG_FILE="${QSM_LOCAL_TTS_LOG_FILE:-$QSM_HOME/data/local-tts.log}"

test -x "$BIN" || {
  echo "[local-tts] missing: $BIN" >&2
  exit 2
}
test -s "$VOICE_ROOT/models/tts/zh_CN-xiao_ya-medium.onnx" || {
  echo "[local-tts] offline voice model is not deployed" >&2
  exit 2
}

mkdir -p "$(dirname "$PID_FILE")"
if [ "$ACTION" = "restart" ] && [ -s "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  case "$old_pid" in
    ''|*[!0-9]*) ;;
    *)
      kill "$old_pid" 2>/dev/null || true
      sleep 1
      kill -9 "$old_pid" 2>/dev/null || true
      ;;
  esac
  rm -f "$PID_FILE"
fi

if [ -s "$PID_FILE" ]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "[local-tts] ready pid=$pid port=$PORT"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

export LD_LIBRARY_PATH="$VOICE_ROOT/runtime/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
start-stop-daemon -S -b -m -p "$PID_FILE" -x "$BIN" -- "$VOICE_ROOT" "$PORT"

count=0
while [ "$count" -lt 150 ]; do
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if netstat -lnt 2>/dev/null | grep -Eq "[:.]${PORT}[[:space:]]"; then
    echo "[local-tts] started pid=$pid port=$PORT"
    exit 0
  fi
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    echo "[local-tts] process exited during model loading" >&2
    tail -30 "$LOG_FILE" 2>/dev/null >&2 || true
    exit 3
  fi
  count=$((count + 1))
  sleep 0.2
done

echo "[local-tts] model loading timed out" >&2
exit 3
