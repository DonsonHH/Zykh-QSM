#!/bin/sh
set -u

BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
VOLUME="${SPK_VOL:-230}"
CHUNK_SECONDS="${CHUNK_SECONDS:-1.2}"
TMP_DIR="${TMPDIR:-/tmp}/zykh-audio-relay"

mkdir -p "$TMP_DIR"

log() {
  printf '[audio-relay] %s\n' "$*"
}

fail_soft() {
  log "WARN: $*"
}

if ! command -v curl >/dev/null 2>&1; then
  fail_soft "curl 不存在，无法发送音频到后端。"
  exit 0
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  fail_soft "ffmpeg 不存在，无法采集本机输出音频。"
  exit 0
fi

SOURCE="${PULSE_SOURCE:-}"
if [ -z "$SOURCE" ] && command -v pactl >/dev/null 2>&1; then
  DEFAULT_SINK="$(pactl get-default-sink 2>/dev/null || true)"
  if [ -n "$DEFAULT_SINK" ]; then
    SOURCE="${DEFAULT_SINK}.monitor"
  fi
fi

if [ -z "$SOURCE" ]; then
  fail_soft "没有找到可用的系统声音 monitor；请设置 PULSE_SOURCE。"
  exit 0
fi

log "开始转发本机声音：source=$SOURCE volume=$VOLUME backend=$BACKEND_URL"
log "按 Ctrl+C 停止。"

while :; do
  OUT="$TMP_DIR/chunk.wav"
  B64="$TMP_DIR/chunk.b64"
  rm -f "$OUT" "$B64"

  ffmpeg -hide_banner -loglevel error \
    -f pulse -i "$SOURCE" \
    -t "$CHUNK_SECONDS" \
    -ac 1 -ar 16000 -sample_fmt s16 \
    "$OUT" >/dev/null 2>&1

  if [ ! -s "$OUT" ]; then
    fail_soft "本轮没有采集到音频。"
    sleep 1
    continue
  fi

  if base64 --help 2>&1 | grep -q -- '-w'; then
    base64 -w0 "$OUT" > "$B64"
  else
    base64 "$OUT" | tr -d '\n' > "$B64"
  fi

  AUDIO_B64="$(cat "$B64")"
  curl -sS -X POST "$BACKEND_URL/api/audio/play" \
    -H 'Content-Type: application/json' \
    --data "{\"audio_base64\":\"$AUDIO_B64\",\"format\":\"wav\",\"volume\":$VOLUME}" >/dev/null \
    || fail_soft "发送音频片段失败。"
done
