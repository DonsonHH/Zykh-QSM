#!/bin/sh
set -eu

ARG_COUNT=$#
DEV=${1:-/dev/ttyACM0}
COMMAND=${2:-PING}
EXPECTED=${3:-}
IS_LIGHT_TEST=0
LIGHT_TARGET=

case "$COMMAND" in
    'CABINET 1'|'CABINET 2'|'CABINET 3')
        IS_LIGHT_TEST=1
        LIGHT_TARGET=${COMMAND#CABINET }
        EXPECTED=${EXPECTED:-"OK $COMMAND"}
        if [ "${ALLOW_LIGHT_COMMANDS:-0}" != "1" ]; then
            echo 'refusing to light a cabinet; set ALLOW_LIGHT_COMMANDS=1 after checking the single connected panel' >&2
            exit 2
        fi
        if [ "$EXPECTED" != "OK $COMMAND" ]; then
            echo "invalid acknowledgement for light test: expected 'OK $COMMAND'" >&2
            exit 2
        fi
        ;;
    PING)
        EXPECTED=${EXPECTED:-PONG}
        ;;
    STATUS)
        EXPECTED=${EXPECTED:-'STATUS OFF'}
        ;;
    OFF)
        EXPECTED=${EXPECTED:-'OK OFF'}
        ;;
    *)
        echo 'unsupported command' >&2
        exit 2
        ;;
esac

if [ "$IS_LIGHT_TEST" = "1" ]; then
    LIGHT_HOLD_SECONDS=${LIGHT_HOLD_SECONDS:-10}
    case "$LIGHT_HOLD_SECONDS" in
        ''|*[!0-9]*)
            echo 'LIGHT_HOLD_SECONDS must be an integer from 0 to 30' >&2
            exit 2
            ;;
    esac
    if [ "$LIGHT_HOLD_SECONDS" -gt 30 ]; then
        echo 'LIGHT_HOLD_SECONDS must be an integer from 0 to 30' >&2
        exit 2
    fi
fi

light_may_be_on=0
uart_open=0
original_stty=
CR=$(printf '\r')

cleanup() {
    exit_status=$?
    trap - EXIT HUP INT TERM
    set +e
    if [ "$light_may_be_on" = "1" ] && [ "$uart_open" = "1" ]; then
        printf 'OFF\r\n' >&8
        cleanup_response=
        IFS= read -r cleanup_response <&8
        printf 'STATUS\r\n' >&8
        cleanup_status=
        IFS= read -r cleanup_status <&8
        printf 'LIGHT_TEST cleanup_off=attempted response=%s cleanup_status=%s\n' \
            "${cleanup_response%"$CR"}" "${cleanup_status%"$CR"}" >&2
    fi
    if [ -n "$original_stty" ]; then
        stty -F "$DEV" "$original_stty" >/dev/null 2>&1 || true
    fi
    exit "$exit_status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ -n "${CABINET_LIGHT_LOCK_FILE:-}" ] || [ -n "${CABINET_LIGHT_DEVICE_DIR:-}" ]; then
    resolved_test_device=$(readlink -f "$DEV" 2>/dev/null || true)
    test_pty_number=${resolved_test_device#/dev/pts/}
    if [ "${CABINET_LIGHT_TEST_MODE:-0}" != "1" ] || \
        [ "$resolved_test_device" = "$test_pty_number" ]; then
        echo 'test-only UART overrides require a PTY and CABINET_LIGHT_TEST_MODE=1' >&2
        exit 2
    fi
    case "$test_pty_number" in
        ''|*[!0-9]*)
            echo 'test-only UART overrides require a PTY and CABINET_LIGHT_TEST_MODE=1' >&2
            exit 2
            ;;
    esac
fi

if [ "$IS_LIGHT_TEST" = "1" ]; then
    if [ "$ARG_COUNT" -lt 1 ]; then
        echo 'an explicit ttyACM device is required for a cabinet light test' >&2
        exit 2
    fi
    cabinet_device_dir=${CABINET_LIGHT_DEVICE_DIR:-/dev}
    set -- "$cabinet_device_dir"/ttyACM*
    if [ "$#" -ne 1 ] || [ ! -c "$1" ]; then
        echo 'exactly one ttyACM controller is required for a cabinet light test' >&2
        exit 2
    fi
    if [ ! -c "$DEV" ]; then
        echo 'the explicit cabinet light device is not a character device' >&2
        exit 2
    fi
    resolved_controller=$(readlink -f "$1")
    resolved_device=$(readlink -f "$DEV")
    if [ "$resolved_controller" != "$resolved_device" ]; then
        echo 'the explicit device does not match the unique ttyACM controller' >&2
        exit 2
    fi
fi

if ! command -v flock >/dev/null 2>&1; then
    echo 'flock is required for exclusive cabinet controller access' >&2
    exit 2
fi
if [ -n "${CABINET_LIGHT_LOCK_FILE:-}" ]; then
    light_lock_file=$CABINET_LIGHT_LOCK_FILE
elif [ -d /userdata/zykh_app/data ]; then
    light_lock_file=/userdata/zykh_app/data/cabinet-light-hardware.lock
else
    light_lock_file="${TMPDIR:-/tmp}/zykh-cabinet-light-hardware.lock"
fi
exec 9>>"$light_lock_file"
if ! flock -n 9; then
    if [ "$IS_LIGHT_TEST" = "1" ]; then
        echo 'another cabinet light test is active; refusing concurrent panel control' >&2
    else
        echo 'cabinet controller is busy; refusing concurrent UART access' >&2
    fi
    exit 3
fi

original_stty=$(stty -F "$DEV" -g)
stty -F "$DEV" 115200 cs8 -cstopb -parenb -ixon -ixoff -crtscts \
    clocal raw -echo min 0 time 30
exec 8<>"$DEV"
uart_open=1

exchange() {
    exchange_command=$1
    exchange_expected=$2
    response=
    printf '%s\r\n' "$exchange_command" >&8
    if ! IFS= read -r response <&8; then
        printf 'COMMAND device=%s baud=115200 text=%s\n' "$DEV" "$exchange_command"
        echo 'RESULT FAIL response timeout' >&2
        return 1
    fi
    response=${response%"$CR"}
    printf 'COMMAND device=%s baud=115200 text=%s\n' "$DEV" "$exchange_command"
    printf 'OUTPUT text=%s\n' "$response"
    if [ "$response" != "$exchange_expected" ]; then
        printf 'RESULT FAIL expected=%s\n' "$exchange_expected" >&2
        return 1
    fi
}

if [ "$IS_LIGHT_TEST" = "0" ]; then
    exchange "$COMMAND" "$EXPECTED"
    echo 'RESULT PASS'
    exit 0
fi

# A light command is a complete, exclusive lifecycle. It starts dark, targets
# exactly one panel, verifies that selection, observes for a bounded interval,
# then turns everything off and verifies the final state.
light_may_be_on=1
exchange OFF 'OK OFF'
exchange STATUS 'STATUS OFF'
light_may_be_on=0

light_may_be_on=1
exchange "$COMMAND" "$EXPECTED"
exchange STATUS "STATUS CABINET $LIGHT_TARGET"
sleep "$LIGHT_HOLD_SECONDS"
exchange OFF 'OK OFF'
exchange STATUS 'STATUS OFF'
light_may_be_on=0

printf 'LIGHT_TEST PASS cabinet=%s final_status=off\n' "$LIGHT_TARGET"
