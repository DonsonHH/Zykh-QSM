#!/bin/sh
set -eu

DEV=${1:-/dev/ttyACM0}
COMMAND=${2:-PING}
EXPECTED=${3:-PONG}

case "$COMMAND" in
    'CABINET 1'|'CABINET 2'|'CABINET 3')
        if [ "${ALLOW_LIGHT_COMMANDS:-0}" != "1" ]; then
            echo 'refusing to light a cabinet; set ALLOW_LIGHT_COMMANDS=1 after checking the target device' >&2
            exit 2
        fi
        ;;
    PING|STATUS|OFF) ;;
    *)
        echo 'unsupported command' >&2
        exit 2
        ;;
esac

tmp=$(mktemp "${TMPDIR:-/tmp}/zykh-cabinet-v2-command.XXXXXX")
original_stty=$(stty -F "$DEV" -g)
cleanup() {
    stty -F "$DEV" "$original_stty" >/dev/null 2>&1 || true
    rm -f "$tmp"
}
trap cleanup EXIT HUP INT TERM

stty -F "$DEV" 115200 cs8 -cstopb -parenb -ixon -ixoff -crtscts \
    clocal raw -echo min 0 time 30
: >"$tmp"
(dd if="$DEV" bs=1 count=64 2>/dev/null >"$tmp") &
reader_pid=$!
sleep 1
printf '%s\r\n' "$COMMAND" >"$DEV"
wait "$reader_pid"

bytes=$(wc -c <"$tmp" | tr -d ' \n')
hex=$(od -An -v -tx1 "$tmp" | tr -d ' \n')
response=$(tr -d '\r\n' <"$tmp")
printf 'COMMAND device=%s baud=115200 text=%s\n' "$DEV" "$COMMAND"
printf 'OUTPUT bytes=%s hex=%s text=%s\n' "$bytes" "$hex" "$response"
if [ "$response" != "$EXPECTED" ]; then
    printf 'RESULT FAIL expected=%s\n' "$EXPECTED"
    exit 1
fi
echo 'RESULT PASS'
