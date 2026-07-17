#!/usr/bin/env sh
set -u

QSM_HOME="${QSM_HOME:-/userdata/zykh_app}"
PORT="${PORT:-8080}"
VITALS_UART_DEVICE="${VITALS_UART_DEVICE:-/dev/ttyS8}"
VITALS_UART_TIMEOUT_SECONDS="${VITALS_UART_TIMEOUT_SECONDS:-16}"
VITALS_UART_STABLE_FRAMES="${VITALS_UART_STABLE_FRAMES:-3}"
VITALS_UART_REFERENCE_FRAMES="${VITALS_UART_REFERENCE_FRAMES:-2}"
VITALS_UART_TEMP_DECIMAL_SCALE="${VITALS_UART_TEMP_DECIMAL_SCALE:-100}"
CAMERA_DEVICE="${CAMERA_DEVICE:-/dev/video23}"
CAMERA_CAPTURE_WIDTH="${CAMERA_CAPTURE_WIDTH:-1280}"
CAMERA_CAPTURE_HEIGHT="${CAMERA_CAPTURE_HEIGHT:-720}"
CAMERA_STREAM_WIDTH="${CAMERA_STREAM_WIDTH:-960}"
CAMERA_STREAM_HEIGHT="${CAMERA_STREAM_HEIGHT:-540}"
CAMERA_STREAM_FPS="${CAMERA_STREAM_FPS:-30}"

cd "$QSM_HOME" || exit 1
mkdir -p "$QSM_HOME/data" "$QSM_HOME/scripts"

if [ -f "$QSM_HOME/scripts/patch_station_gateway.pl" ]; then
  perl "$QSM_HOME/scripts/patch_station_gateway.pl" "$QSM_HOME/server.pl" || exit 1
fi

if [ -x "$QSM_HOME/scripts/start_local_tts_server.sh" ]; then
  sh "$QSM_HOME/scripts/start_local_tts_server.sh" >/dev/null 2>&1 || \
    printf 'Warning: persistent offline TTS did not start; script fallback remains available.\n' >&2
fi

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

stop_count=0
while [ -n "$(gateway_pids)" ] && [ "$stop_count" -lt 20 ]; do
  stop_count=$((stop_count + 1))
  sleep 0.2
done
for pid in $(gateway_pids); do
  kill -9 "$pid" 2>/dev/null || true
done
sleep 0.3

if [ -n "$(gateway_pids)" ]; then
  printf 'Cannot stop the previous station gateway processes\n' >&2
  exit 1
fi

TZ="${TZ:-CST-8}" \
PORT="$PORT" \
MAX30102_SCRIPT="$QSM_HOME/scripts/read_vitals_uart8.pl" \
MAX30102_JSON="$QSM_HOME/data/vital_signs_uart8.json" \
VITALS_UART_DEVICE="$VITALS_UART_DEVICE" \
VITALS_UART_TIMEOUT_SECONDS="$VITALS_UART_TIMEOUT_SECONDS" \
VITALS_UART_STABLE_FRAMES="$VITALS_UART_STABLE_FRAMES" \
VITALS_UART_REFERENCE_FRAMES="$VITALS_UART_REFERENCE_FRAMES" \
VITALS_UART_TEMP_DECIMAL_SCALE="$VITALS_UART_TEMP_DECIMAL_SCALE" \
CAMERA_DEVICE="$CAMERA_DEVICE" \
CAMERA_CAPTURE_WIDTH="$CAMERA_CAPTURE_WIDTH" \
CAMERA_CAPTURE_HEIGHT="$CAMERA_CAPTURE_HEIGHT" \
CAMERA_STREAM_WIDTH="$CAMERA_STREAM_WIDTH" \
CAMERA_STREAM_HEIGHT="$CAMERA_STREAM_HEIGHT" \
CAMERA_STREAM_FPS="$CAMERA_STREAM_FPS" \
AI_MODEL="${AI_MODEL:-deepseek-v4-flash}" \
perl "$QSM_HOME/server.pl" --daemon >"$QSM_HOME/server.log" 2>&1 </dev/null

sleep 1
if [ -n "$(gateway_pids)" ]; then
  printf 'ZYKH station gateway started on port %s with camera %s and vitals UART %s\n' "$PORT" "$CAMERA_DEVICE" "$VITALS_UART_DEVICE"
  exit 0
fi

printf 'ZYKH station gateway failed; see %s/server.log\n' "$QSM_HOME" >&2
tail -80 "$QSM_HOME/server.log" 2>/dev/null
exit 1
