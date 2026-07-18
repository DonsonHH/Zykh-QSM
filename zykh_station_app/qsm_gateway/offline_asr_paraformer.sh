#!/bin/sh
set -eu

VOICE_ROOT="${ZYKH_VOICE_ROOT:-/userdata/zykh_voice}"
BIN="$VOICE_ROOT/runtime/bin/sherpa-onnx-offline"
MODEL_DIR="$VOICE_ROOT/models/asr-paraformer"
INPUT_WAV="${1:-}"

if [ -z "$INPUT_WAV" ] || [ ! -s "$INPUT_WAV" ]; then
  echo "input wav is missing or empty: $INPUT_WAV" >&2
  exit 2
fi

for file in "$BIN" "$MODEL_DIR/model.int8.onnx" "$MODEL_DIR/tokens.txt"; do
  if [ ! -s "$file" ]; then
    echo "Paraformer ASR file is missing: $file" >&2
    exit 3
  fi
done

export LD_LIBRARY_PATH="$VOICE_ROOT/runtime/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export OMP_NUM_THREADS="${ASR_THREADS:-2}"

exec "$BIN" \
  --model-type=paraformer \
  --tokens="$MODEL_DIR/tokens.txt" \
  --paraformer="$MODEL_DIR/model.int8.onnx" \
  --num-threads="${ASR_THREADS:-2}" \
  "$INPUT_WAV"
