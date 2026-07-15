#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VERSION="${SHERPA_ONNX_VERSION:-1.13.2}"
CACHE_DIR="${SHERPA_BUILD_CACHE:-/tmp/zykh-local-tts-build}"
HEADER_URL="https://raw.githubusercontent.com/k2-fsa/sherpa-onnx/v${VERSION}/sherpa-onnx/c-api/c-api.h"
BOARD_LIB="${QSM_TTS_C_API_LIB:-/tmp/qsm-sherpa-tts-c-api.so}"
OUTPUT="$CACHE_DIR/local-tts-server"

for command in adb curl aarch64-linux-gnu-g++; do
  command -v "$command" >/dev/null 2>&1 || {
    printf '[local-tts] missing host command: %s\n' "$command" >&2
    exit 1
  }
done

mkdir -p "$CACHE_DIR/include/sherpa-onnx/c-api"
curl -fsSL --retry 3 -o "$CACHE_DIR/include/sherpa-onnx/c-api/c-api.h" "$HEADER_URL"
adb pull /userdata/zykh_voice/runtime/lib/libsherpa-onnx-c-api.so "$BOARD_LIB" >/dev/null
aarch64-linux-gnu-g++ -std=c++17 -O2 -Wall -Wextra \
  -I"$CACHE_DIR/include" \
  "$ROOT_DIR/qsm_gateway/local_tts_server.cpp" \
  "$BOARD_LIB" \
  -Wl,--allow-shlib-undefined \
  -Wl,-rpath,/userdata/zykh_voice/runtime/lib \
  -o "$OUTPUT"

adb shell 'mkdir -p /userdata/zykh_app/bin /userdata/zykh_app/scripts /userdata/zykh_app/data'
adb push "$OUTPUT" /userdata/zykh_app/bin/local-tts-server >/dev/null
adb push "$ROOT_DIR/qsm_gateway/start_local_tts_server.sh" /userdata/zykh_app/scripts/start_local_tts_server.sh >/dev/null
adb shell 'chmod 755 /userdata/zykh_app/bin/local-tts-server /userdata/zykh_app/scripts/start_local_tts_server.sh; sh /userdata/zykh_app/scripts/start_local_tts_server.sh'

printf '[local-tts] persistent service deployed on QSM port 19002.\n'
