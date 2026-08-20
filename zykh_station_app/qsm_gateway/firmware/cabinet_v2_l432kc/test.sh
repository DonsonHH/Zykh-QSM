#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
HOST_CC=${HOST_CC:-cc}
HOST_TEST_DIR=$(mktemp -d "${TMPDIR:-/tmp}/zykh-cabinet-v2-test.XXXXXX")
cleanup() {
    rm -rf "$HOST_TEST_DIR"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

python3 "$ROOT/tests/test_firmware_contract.py"
"$HOST_CC" -std=c11 -Wall -Wextra -Werror -DCABINET_V2_HOST_TEST \
    "$ROOT/main.c" "$ROOT/tests/test_led_pattern.c" \
    -o "$HOST_TEST_DIR/test_led_pattern"
"$HOST_TEST_DIR/test_led_pattern"
python3 "$ROOT/tests/test_serial_command_safety.py"
sh -n "$ROOT/build.sh"
sh -n "$ROOT/test.sh"
sh -n "$ROOT/tools/serial_command_test.sh"

if [ "${FIRMWARE_TEST_BUILD:-0}" = "1" ]; then
    "$ROOT/build.sh"
fi
