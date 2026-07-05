#!/bin/sh
set -u

BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
VOLUME="${SPK_VOL:-230}"
CHUNK_SECONDS="${CHUNK_SECONDS:-1.2}"
TMP_DIR="${TMPDIR:-/tmp}/zykh-audio-relay"
SINK_NAME="${QSM_AUDIO_SINK_NAME:-qsm_relay}"
CREATE_SINK="${QSM_AUDIO_CREATE_SINK:-1}"
SET_DEFAULT="${QSM_AUDIO_SET_DEFAULT:-1}"
MOVE_EXISTING="${QSM_AUDIO_MOVE_EXISTING:-1}"
RESTORE_ON_EXIT="${QSM_AUDIO_RESTORE_ON_EXIT:-1}"
UNLOAD_ON_EXIT="${QSM_AUDIO_UNLOAD_SINK_ON_EXIT:-1}"
ORIGINAL_SINK=""
CREATED_MODULE_ID=""

mkdir -p "$TMP_DIR"

log() {
  printf '[audio-relay] %s\n' "$*"
}

fail_soft() {
  log "WARN: $*"
}

cleanup() {
  if [ "$RESTORE_ON_EXIT" = "1" ] && [ -n "$ORIGINAL_SINK" ] && command -v pactl >/dev/null 2>&1; then
    pactl set-default-sink "$ORIGINAL_SINK" >/dev/null 2>&1 || true
    log "已恢复默认音频输出：$ORIGINAL_SINK"
  fi
  if [ "$UNLOAD_ON_EXIT" = "1" ] && [ -n "$CREATED_MODULE_ID" ] && command -v pactl >/dev/null 2>&1; then
    pactl unload-module "$CREATED_MODULE_ID" >/dev/null 2>&1 || true
    log "已卸载本机音频转发虚拟输出。"
  fi
}

trap cleanup INT TERM EXIT

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
  ORIGINAL_SINK="$DEFAULT_SINK"

  if [ "$CREATE_SINK" = "1" ]; then
    if ! pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -qx "$SINK_NAME"; then
      CREATED_MODULE_ID="$(pactl load-module module-null-sink sink_name="$SINK_NAME" sink_properties=device.description=QSM-Speaker 2>/dev/null || true)"
      if [ -n "$CREATED_MODULE_ID" ]; then
        log "已创建本机音频转发虚拟输出：$SINK_NAME"
      else
        fail_soft "无法创建虚拟输出 $SINK_NAME，将尝试使用当前默认输出 monitor。"
      fi
    fi
  fi

  if pactl list short sinks 2>/dev/null | awk '{print $2}' | grep -qx "$SINK_NAME"; then
    SOURCE="${SINK_NAME}.monitor"
    if [ "$SET_DEFAULT" = "1" ]; then
      pactl set-default-sink "$SINK_NAME" >/dev/null 2>&1 || true
      log "已将本机默认音频输出切换到：$SINK_NAME"
    fi
    if [ "$MOVE_EXISTING" = "1" ]; then
      pactl list short sink-inputs 2>/dev/null | awk '{print $1}' | while read -r input_id; do
        [ -n "$input_id" ] && pactl move-sink-input "$input_id" "$SINK_NAME" >/dev/null 2>&1 || true
      done
    fi
  elif [ -n "$DEFAULT_SINK" ]; then
    SOURCE="${DEFAULT_SINK}.monitor"
  fi
fi

if [ -z "$SOURCE" ]; then
  fail_soft "没有找到可用的系统声音 monitor；请设置 PULSE_SOURCE，或确认 pactl/PulseAudio/PipeWire 正常。"
  exit 0
fi

log "开始转发本机声音：source=$SOURCE volume=$VOLUME backend=$BACKEND_URL"
log "说明：这是用户态虚拟声卡转发，不是内核驱动；新打开的应用会跟随默认输出，已打开的应用会尽量自动迁移。"
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
