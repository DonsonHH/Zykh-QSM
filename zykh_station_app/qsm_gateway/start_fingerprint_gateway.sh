#!/usr/bin/env sh
set -u

QSM_FINGERPRINT_HOME="${QSM_FINGERPRINT_HOME:-/userdata/qsm-fingerprint}"
QSM_FINGERPRINT_PORT="${QSM_FINGERPRINT_PORT:-8086}"
GATEWAY="$QSM_FINGERPRINT_HOME/fingerprint_gateway.pl"
INIT_SCRIPT="${QSM_FINGERPRINT_INIT:-/userdata/zykh_app/scripts/init_fingerprint.sh}"
PID_FILE="$QSM_FINGERPRINT_HOME/fingerprint-gateway.pid"
LOG_FILE="$QSM_FINGERPRINT_HOME/logs/fingerprint-gateway.log"

mkdir -p "$QSM_FINGERPRINT_HOME/logs"

if [ -x "$INIT_SCRIPT" ]; then
  sh "$INIT_SCRIPT" start >>"$LOG_FILE" 2>&1 || {
    printf 'QSM fingerprint initialization failed; see %s\n' "$LOG_FILE" >&2
    exit 1
  }
fi

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

QSM_FINGERPRINT_PORT="$QSM_FINGERPRINT_PORT" \
QSM_FINGERPRINT_DRIVER="${QSM_FINGERPRINT_DRIVER:-/userdata/zykh_app/scripts/as608.pl}" \
QSM_FINGERPRINT_INIT="$INIT_SCRIPT" \
nohup perl "$GATEWAY" >>"$LOG_FILE" 2>&1 </dev/null &
pid="$!"
echo "$pid" >"$PID_FILE"
sleep 1

if kill -0 "$pid" 2>/dev/null; then
  printf 'QSM fingerprint gateway started on port %s, pid=%s\n' "$QSM_FINGERPRINT_PORT" "$pid"
  exit 0
fi

rm -f "$PID_FILE"
printf 'QSM fingerprint gateway failed; see %s\n' "$LOG_FILE" >&2
tail -80 "$LOG_FILE" 2>/dev/null
exit 1
