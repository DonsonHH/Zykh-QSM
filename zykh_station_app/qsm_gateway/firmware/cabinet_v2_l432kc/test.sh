#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

python3 "$ROOT/tests/test_firmware_contract.py"
sh -n "$ROOT/build.sh"
sh -n "$ROOT/test.sh"
sh -n "$ROOT/tools/serial_command_test.sh"

if [ "${FIRMWARE_TEST_BUILD:-0}" = "1" ]; then
    "$ROOT/build.sh"
fi
