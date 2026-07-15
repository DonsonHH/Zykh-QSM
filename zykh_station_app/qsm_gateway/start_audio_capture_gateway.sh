#!/usr/bin/env sh
set -u

QSM_AUDIO_HOME="${QSM_AUDIO_HOME:-/userdata/qsm-audio}"
QSM_AUDIO_CAPTURE_PORT="${QSM_AUDIO_CAPTURE_PORT:-8082}"
GATEWAY="$QSM_AUDIO_HOME/audio_capture_gateway.pl"
PID_FILE="$QSM_AUDIO_HOME/audio-capture-gateway.pid"
LOG_FILE="$QSM_AUDIO_HOME/logs/audio-capture-gateway.log"

mkdir -p "$QSM_AUDIO_HOME/logs"

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
    *"perl $GATEWAY"*) kill "${process##*/}" 2>/dev/null || true ;;
  esac
done
sleep 1

QSM_AUDIO_CAPTURE_PORT="$QSM_AUDIO_CAPTURE_PORT" \
nohup perl "$GATEWAY" >>"$LOG_FILE" 2>&1 </dev/null &
pid="$!"
echo "$pid" >"$PID_FILE"
sleep 1

if kill -0 "$pid" 2>/dev/null; then
  printf 'QSM audio capture gateway started on port %s, pid=%s\n' "$QSM_AUDIO_CAPTURE_PORT" "$pid"
  exit 0
fi

rm -f "$PID_FILE"
printf 'QSM audio capture gateway failed; see %s\n' "$LOG_FILE" >&2
tail -80 "$LOG_FILE" 2>/dev/null
exit 1
