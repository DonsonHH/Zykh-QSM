#!/usr/bin/env sh
set -u

QSM_HOME="${QSM_HOME:-/userdata/zykh_app}"
PORT="${PORT:-8080}"
VITALS_UART_DEVICE="${VITALS_UART_DEVICE:-/dev/ttyS8}"
VITALS_UART_TIMEOUT_SECONDS="${VITALS_UART_TIMEOUT_SECONDS:-16}"
VITALS_UART_STABLE_FRAMES="${VITALS_UART_STABLE_FRAMES:-3}"
VITALS_UART_REFERENCE_FRAMES="${VITALS_UART_REFERENCE_FRAMES:-2}"
VITALS_UART_TEMP_DECIMAL_SCALE="${VITALS_UART_TEMP_DECIMAL_SCALE:-100}"

cd "$QSM_HOME" || exit 1
mkdir -p "$QSM_HOME/data" "$QSM_HOME/scripts"

gateway_pids() {
  for process in /proc/[0-9]*; do
    [ -r "$process/cmdline" ] || continue
    command_line="$(tr '\000' ' ' <"$process/cmdline" 2>/dev/null)"
    case "$command_line" in
      *"perl $QSM_HOME/server.pl"*|*"perl server.pl"*)
        printf '%s\n' "${process##*/}"
        ;;
    esac
  done
}

for pid in $(gateway_pids); do
  kill "$pid" 2>/dev/null || true
done
sleep 1

TZ="${TZ:-CST-8}" \
PORT="$PORT" \
MAX30102_SCRIPT="$QSM_HOME/scripts/read_vitals_uart8.pl" \
MAX30102_JSON="$QSM_HOME/data/vital_signs_uart8.json" \
VITALS_UART_DEVICE="$VITALS_UART_DEVICE" \
VITALS_UART_TIMEOUT_SECONDS="$VITALS_UART_TIMEOUT_SECONDS" \
VITALS_UART_STABLE_FRAMES="$VITALS_UART_STABLE_FRAMES" \
VITALS_UART_REFERENCE_FRAMES="$VITALS_UART_REFERENCE_FRAMES" \
VITALS_UART_TEMP_DECIMAL_SCALE="$VITALS_UART_TEMP_DECIMAL_SCALE" \
AI_MODEL="${AI_MODEL:-deepseek-v4-flash}" \
perl "$QSM_HOME/server.pl" --daemon >"$QSM_HOME/server.log" 2>&1 </dev/null

sleep 1
if [ -n "$(gateway_pids)" ]; then
  printf 'ZYKH station gateway started on port %s with vitals UART %s\n' "$PORT" "$VITALS_UART_DEVICE"
  exit 0
fi

printf 'ZYKH station gateway failed; see %s/server.log\n' "$QSM_HOME" >&2
tail -80 "$QSM_HOME/server.log" 2>/dev/null
exit 1
