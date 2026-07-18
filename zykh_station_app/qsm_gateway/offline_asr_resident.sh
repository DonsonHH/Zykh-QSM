#!/bin/sh
set -eu

APP_ROOT="${ZYKH_APP_ROOT:-/userdata/zykh_app}"
CLIENT="$APP_ROOT/scripts/asr_ws_client.pl"
SERVICE="$APP_ROOT/scripts/start_asr_service.sh"
INPUT_WAV="${1:-}"

if [ -z "$INPUT_WAV" ] || [ ! -s "$INPUT_WAV" ]; then
  echo "input wav is missing or empty: $INPUT_WAV" >&2
  exit 2
fi

if ! "$SERVICE" status >/dev/null 2>&1; then
  "$SERVICE" start >/dev/null
fi

exec /usr/bin/perl "$CLIENT" "$INPUT_WAV"
