#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
VERSION="${SHERPA_ONNX_VERSION:-1.13.2}"
RUNTIME_ARCHIVE="sherpa-onnx-v${VERSION}-linux-aarch64-shared-cpu.tar.bz2"
MODEL_NAME="sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
MODEL_ARCHIVE="${MODEL_NAME}.tar.bz2"
RUNTIME_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/v${VERSION}/${RUNTIME_ARCHIVE}"
MODEL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${MODEL_ARCHIVE}"
CACHE_DIR="${SHERPA_DOWNLOAD_CACHE:-/tmp/zykh-local-asr}"
REMOTE_ROOT="${QSM_LOCAL_ASR_ROOT:-/userdata/zykh_app/local_asr}"

for command in adb curl tar; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "[local-asr] missing host command: $command" >&2
    exit 1
  }
done

mkdir -p "$CACHE_DIR/runtime" "$CACHE_DIR/model"
if [ ! -s "$CACHE_DIR/$RUNTIME_ARCHIVE" ]; then
  curl -fL --retry 3 -o "$CACHE_DIR/$RUNTIME_ARCHIVE" "$RUNTIME_URL"
fi
if [ ! -s "$CACHE_DIR/$MODEL_ARCHIVE" ]; then
  curl -fL --retry 3 -o "$CACHE_DIR/$MODEL_ARCHIVE" "$MODEL_URL"
fi

rm -rf "$CACHE_DIR/runtime" "$CACHE_DIR/model"
mkdir -p "$CACHE_DIR/runtime" "$CACHE_DIR/model"
tar -xjf "$CACHE_DIR/$RUNTIME_ARCHIVE" -C "$CACHE_DIR/runtime" --strip-components=1
tar -xjf "$CACHE_DIR/$MODEL_ARCHIVE" -C "$CACHE_DIR/model"
MODEL_DIR="$CACHE_DIR/model/$MODEL_NAME"

adb shell "mkdir -p '$REMOTE_ROOT/bin' '$REMOTE_ROOT/lib' '$REMOTE_ROOT/model' /userdata/zykh_app/scripts /userdata/zykh_app/data"
adb push "$CACHE_DIR/runtime/bin/sherpa-onnx-online-websocket-server" "$REMOTE_ROOT/bin/"
adb push \
  "$CACHE_DIR/runtime/lib/libonnxruntime.so" \
  "$CACHE_DIR/runtime/lib/libsherpa-onnx-c-api.so" \
  "$CACHE_DIR/runtime/lib/libsherpa-onnx-cxx-api.so" \
  "$REMOTE_ROOT/lib/"
adb push \
  "$MODEL_DIR/encoder.int8.onnx" \
  "$MODEL_DIR/decoder.onnx" \
  "$MODEL_DIR/joiner.int8.onnx" \
  "$MODEL_DIR/tokens.txt" \
  "$REMOTE_ROOT/model/"
adb push "$ROOT_DIR/qsm_gateway/asr_hotwords.txt" "$REMOTE_ROOT/model/hotwords.txt"
adb push "$ROOT_DIR/scripts/start_local_asr.sh" /userdata/zykh_app/scripts/start_local_asr.sh
adb shell "chmod +x '$REMOTE_ROOT/bin/sherpa-onnx-online-websocket-server' /userdata/zykh_app/scripts/start_local_asr.sh"
adb shell "QSM_LOCAL_ASR_ROOT='$REMOTE_ROOT' QSM_LOCAL_ASR_RESTART=1 sh /userdata/zykh_app/scripts/start_local_asr.sh"
adb forward tcp:18084 tcp:8084 >/dev/null

echo "[local-asr] deployed to $REMOTE_ROOT"
echo "[local-asr] host websocket: ws://127.0.0.1:18084"
