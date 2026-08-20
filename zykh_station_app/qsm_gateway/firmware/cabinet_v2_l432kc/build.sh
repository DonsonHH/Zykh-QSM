#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OUT=${1:-"$ROOT/build"}
EXPECTED_BIN_SHA256=91776e0fac42163f7151fb0e1c4df6cf2c2bb81b8e80c17581a77523776813db

if [ -n "${TOOLCHAIN:-}" ]; then
    CC=${CC:-"$TOOLCHAIN/arm-none-eabi-gcc"}
    OBJCOPY=${OBJCOPY:-"$TOOLCHAIN/arm-none-eabi-objcopy"}
    SIZE=${SIZE:-"$TOOLCHAIN/arm-none-eabi-size"}
else
    CC=${CC:-arm-none-eabi-gcc}
    OBJCOPY=${OBJCOPY:-arm-none-eabi-objcopy}
    SIZE=${SIZE:-arm-none-eabi-size}
fi

for tool in "$CC" "$OBJCOPY" "$SIZE"; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'missing ARM toolchain command: %s\n' "$tool" >&2
        exit 127
    fi
done

mkdir -p "$OUT"
"$CC" \
    -mcpu=cortex-m4 -mthumb -Os -ffreestanding -fno-builtin \
    -ffunction-sections -fdata-sections -nostdlib \
    -Wl,-T,"$ROOT/linker.ld",--gc-sections,--build-id=none \
    -Wl,-Map,"$OUT/firmware.map" \
    -o "$OUT/firmware.elf" "$ROOT/main.c"
"$OBJCOPY" -O binary "$OUT/firmware.elf" "$OUT/firmware.bin"
"$OBJCOPY" -O ihex "$OUT/firmware.elf" "$OUT/firmware.hex"
"$SIZE" "$OUT/firmware.elf"

actual_sha256=$(sha256sum "$OUT/firmware.bin" | awk '{print $1}')
printf 'BIN_SHA256 %s\n' "$actual_sha256"
if [ "$actual_sha256" != "$EXPECTED_BIN_SHA256" ]; then
    printf 'firmware hash mismatch; expected %s\n' "$EXPECTED_BIN_SHA256" >&2
    exit 1
fi
