#!/bin/sh
set -eu

VOICE_ROOT="${ZYKH_VOICE_ROOT:-/userdata/zykh_voice}"
BIN="$VOICE_ROOT/runtime/bin/sherpa-onnx-offline-tts"
MODEL_DIR="$VOICE_ROOT/models/tts"
TEXT="${1:-}"
OUTPUT_WAV="${2:-}"

if [ -z "$TEXT" ] || [ -z "$OUTPUT_WAV" ]; then
    echo "usage: offline_tts.sh TEXT OUTPUT_WAV" >&2
    exit 2
fi

for file in \
    "$BIN" \
    "$MODEL_DIR/zh_CN-xiao_ya-medium.onnx" \
    "$MODEL_DIR/lexicon.txt" \
    "$MODEL_DIR/tokens.txt" \
    "$MODEL_DIR/phone.fst" \
    "$MODEL_DIR/date.fst" \
    "$MODEL_DIR/number.fst"; do
    if [ ! -s "$file" ]; then
        echo "offline TTS file is missing: $file" >&2
        exit 3
    fi
done

mkdir -p "$(dirname "$OUTPUT_WAV")"
rm -f "$OUTPUT_WAV"

export LD_LIBRARY_PATH="$VOICE_ROOT/runtime/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export OMP_NUM_THREADS="${TTS_THREADS:-2}"

"$BIN" \
    --vits-model="$MODEL_DIR/zh_CN-xiao_ya-medium.onnx" \
    --vits-lexicon="$MODEL_DIR/lexicon.txt" \
    --vits-tokens="$MODEL_DIR/tokens.txt" \
    --tts-rule-fsts="$MODEL_DIR/phone.fst,$MODEL_DIR/date.fst,$MODEL_DIR/number.fst" \
    --vits-length-scale="${TTS_LENGTH_SCALE:-1.0}" \
    --num-threads="${TTS_THREADS:-2}" \
    --output-filename="$OUTPUT_WAV" \
    "$TEXT"

test -s "$OUTPUT_WAV"
