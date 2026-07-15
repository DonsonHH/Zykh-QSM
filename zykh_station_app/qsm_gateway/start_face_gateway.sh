#!/usr/bin/env sh
set -u

QSM_FACE_HOME="${QSM_FACE_HOME:-/userdata/qsm-face}"
QSM_FACE_GATEWAY_PORT="${QSM_FACE_GATEWAY_PORT:-8081}"
QSM_FACE_GATEWAY="${QSM_FACE_GATEWAY:-$QSM_FACE_HOME/face_gateway.pl}"
PID_FILE="$QSM_FACE_HOME/face-gateway.pid"
LOG_FILE="$QSM_FACE_HOME/logs/face-gateway.log"

mkdir -p "$QSM_FACE_HOME/logs" "$QSM_FACE_HOME/data"

if [ -f "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  case "$old_pid" in
    ''|*[!0-9]*) ;;
    *) kill "$old_pid" 2>/dev/null || true ;;
  esac
  rm -f "$PID_FILE"
fi

for process in /proc/[0-9]*; do
  [ -r "$process/cmdline" ] || continue
  command_line="$(tr '\000' ' ' <"$process/cmdline" 2>/dev/null)"
  case "$command_line" in
    *"perl $QSM_FACE_GATEWAY"*) kill "${process##*/}" 2>/dev/null || true ;;
  esac
done
sleep 1

QSM_FACE_HOME="$QSM_FACE_HOME" \
QSM_FACE_GATEWAY_PORT="$QSM_FACE_GATEWAY_PORT" \
nohup perl "$QSM_FACE_GATEWAY" >>"$LOG_FILE" 2>&1 </dev/null &
pid="$!"
echo "$pid" >"$PID_FILE"
sleep 1

if kill -0 "$pid" 2>/dev/null; then
  printf 'QSM face gateway started on port %s, pid=%s\n' "$QSM_FACE_GATEWAY_PORT" "$pid"
  exit 0
fi

rm -f "$PID_FILE"
printf 'QSM face gateway failed; see %s\n' "$LOG_FILE" >&2
tail -80 "$LOG_FILE" 2>/dev/null
exit 1
