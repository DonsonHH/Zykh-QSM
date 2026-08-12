#!/usr/bin/env sh
set -u

QSM_VITALS_HOME="${QSM_VITALS_HOME:-/userdata/qsm-vitals}"
QSM_VITALS_PORT="${QSM_VITALS_PORT:-8085}"
GATEWAY="$QSM_VITALS_HOME/vitals_gateway.pl"
PID_FILE="$QSM_VITALS_HOME/vitals-gateway.pid"
LOG_FILE="$QSM_VITALS_HOME/logs/vitals-gateway.log"

mkdir -p "$QSM_VITALS_HOME/data" "$QSM_VITALS_HOME/logs"

if [ -f "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  case "$old_pid" in
    ''|*[!0-9]*) ;;
    *)
      kill "$old_pid" 2>/dev/null || true
      count=0
      while kill -0 "$old_pid" 2>/dev/null && [ "$count" -lt 30 ]; do
        count=$((count + 1))
        sleep 0.1
      done
      if kill -0 "$old_pid" 2>/dev/null; then
        kill -KILL "$old_pid" 2>/dev/null || true
        sleep 0.2
      fi
      ;;
  esac
  rm -f "$PID_FILE"
fi

QSM_VITALS_HOME="$QSM_VITALS_HOME" QSM_VITALS_PORT="$QSM_VITALS_PORT" \
  nohup perl "$GATEWAY" >>"$LOG_FILE" 2>&1 </dev/null &
pid="$!"
echo "$pid" >"$PID_FILE"
sleep 1

if kill -0 "$pid" 2>/dev/null; then
  printf 'QSM vitals gateway started on port %s, pid=%s\n' "$QSM_VITALS_PORT" "$pid"
  exit 0
fi

rm -f "$PID_FILE"
printf 'QSM vitals gateway failed; see %s\n' "$LOG_FILE" >&2
tail -80 "$LOG_FILE" 2>/dev/null
exit 1
