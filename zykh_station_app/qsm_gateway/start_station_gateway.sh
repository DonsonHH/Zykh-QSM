#!/usr/bin/env sh
set -u

QSM_HOME="${QSM_HOME:-/userdata/zykh_app}"
PORT="${PORT:-8080}"
CABINET_LIGHT_UART="${CABINET_LIGHT_UART:-/dev/ttyACM0}"
CABINET_LIGHT_UART_BAUD="${CABINET_LIGHT_UART_BAUD:-115200}"
CABINET_LIGHT_TIMEOUT_SECONDS="${CABINET_LIGHT_TIMEOUT_SECONDS:-2}"
CABINET_LIGHT_PROTOCOL_MODULE="${CABINET_LIGHT_PROTOCOL_MODULE:-$QSM_HOME/scripts/Zykh/CabinetLightProtocol.pm}"
VITALS_UART_DEVICE="${VITALS_UART_DEVICE:-/dev/ttyS8}"
VITALS_UART_TIMEOUT_SECONDS="${VITALS_UART_TIMEOUT_SECONDS:-16}"
VITALS_UART_STABLE_FRAMES="${VITALS_UART_STABLE_FRAMES:-3}"
VITALS_UART_REFERENCE_FRAMES="${VITALS_UART_REFERENCE_FRAMES:-2}"
VITALS_UART_TEMP_DECIMAL_SCALE="${VITALS_UART_TEMP_DECIMAL_SCALE:-100}"
CAMERA_DEVICE="${CAMERA_DEVICE:-/dev/video23}"
CAMERA_CAPTURE_WIDTH="${CAMERA_CAPTURE_WIDTH:-1280}"
CAMERA_CAPTURE_HEIGHT="${CAMERA_CAPTURE_HEIGHT:-720}"
CAMERA_STREAM_WIDTH="${CAMERA_STREAM_WIDTH:-1280}"
CAMERA_STREAM_HEIGHT="${CAMERA_STREAM_HEIGHT:-720}"
CAMERA_STREAM_FPS="${CAMERA_STREAM_FPS:-30}"

cd "$QSM_HOME" || exit 1
mkdir -p "$QSM_HOME/data" "$QSM_HOME/scripts"

# The board-side TTS service was retired. Stop an older deployment if one is
# still running so its model cannot compete with ASR or the local AI process.
legacy_tts_pid_file="$QSM_HOME/data/local-tts.pid"
if [ -s "$legacy_tts_pid_file" ]; then
  legacy_tts_pid="$(cat "$legacy_tts_pid_file" 2>/dev/null || true)"
  case "$legacy_tts_pid" in
    ''|*[!0-9]*) ;;
    *) kill "$legacy_tts_pid" 2>/dev/null || true; sleep 1; kill -9 "$legacy_tts_pid" 2>/dev/null || true ;;
  esac
  rm -f "$legacy_tts_pid_file"
fi
if command -v pidof >/dev/null 2>&1; then
  for legacy_tts_pid in $(pidof local-tts-server 2>/dev/null || true); do
    kill "$legacy_tts_pid" 2>/dev/null || true
  done
fi

if [ -f "$QSM_HOME/scripts/patch_station_gateway.pl" ]; then
  perl "$QSM_HOME/scripts/patch_station_gateway.pl" "$QSM_HOME/server.pl" || exit 1
fi

if [ -x "$QSM_HOME/scripts/start_asr_service.sh" ]; then
  "$QSM_HOME/scripts/start_asr_service.sh" start >/dev/null 2>&1 || \
    printf 'Warning: resident Paraformer ASR did not start; cloud recognition remains available.\n' >&2
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

if [ ! -r "$CABINET_LIGHT_PROTOCOL_MODULE" ]; then
  printf 'Cabinet light protocol module is missing: %s\n' "$CABINET_LIGHT_PROTOCOL_MODULE" >&2
  exit 1
fi

# A previous process or interrupted interaction may have left one cabinet lit.
# Confirm OFF over the same strict protocol before accepting new requests.
if ! perl - "$CABINET_LIGHT_PROTOCOL_MODULE" "$CABINET_LIGHT_UART" "$CABINET_LIGHT_UART_BAUD" "$CABINET_LIGHT_TIMEOUT_SECONDS" <<'PERL'
use strict;
use warnings;
my ($module, $device, $baud, $timeout) = @ARGV;
require $module;
my $protocol = Zykh::CabinetLightProtocol->new(
    device => $device,
    baud => int($baud),
    timeout_seconds => 0 + $timeout,
);
my $result = $protocol->off();
if (!$result->{ok}) {
    print STDERR (($result->{detail} || $result->{error} || 'cabinet light OFF failed') . "\n");
    exit 1;
}
PERL
then
  printf 'Cannot confirm cabinet lights are OFF; station gateway will not start.\n' >&2
  exit 1
fi

TZ="${TZ:-CST-8}" \
PORT="$PORT" \
CABINET_LIGHT_PROTOCOL_MODULE="$CABINET_LIGHT_PROTOCOL_MODULE" \
CABINET_LIGHT_UART="$CABINET_LIGHT_UART" \
CABINET_LIGHT_UART_BAUD="$CABINET_LIGHT_UART_BAUD" \
CABINET_LIGHT_TIMEOUT_SECONDS="$CABINET_LIGHT_TIMEOUT_SECONDS" \
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
