#!/bin/sh
set -u

BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
VOLUME="${SPK_VOL:-230}"
USE_STREAM="${QSM_AUDIO_USE_STREAM:-1}"
STREAM_PORT="${QSM_AUDIO_STREAM_PORT:-19001}"
HOST_STREAM_PORT="${QSM_AUDIO_HOST_STREAM_PORT:-19001}"
STREAM_RATE="${QSM_AUDIO_STREAM_RATE:-16000}"
TMP_DIR="${TMPDIR:-/tmp}/zykh-audio-relay"
SINK_NAME="${QSM_AUDIO_SINK_NAME:-qsm_relay}"
CREATE_SINK="${QSM_AUDIO_CREATE_SINK:-1}"
SET_DEFAULT="${QSM_AUDIO_SET_DEFAULT:-1}"
MOVE_EXISTING="${QSM_AUDIO_MOVE_EXISTING:-1}"
RESTORE_ON_EXIT="${QSM_AUDIO_RESTORE_ON_EXIT:-1}"
UNLOAD_ON_EXIT="${QSM_AUDIO_UNLOAD_SINK_ON_EXIT:-1}"
ORIGINAL_SINK=""
CREATED_MODULE_ID=""
PRODUCER_PID=""
STREAM_ACTIVE="0"
CLEANED_UP="0"

mkdir -p "$TMP_DIR"

log() {
  printf '[audio-relay] %s\n' "$*"
}

fail_soft() {
  log "WARN: $*"
}

fail_hard() {
  log "FAIL: $*"
  exit 1
}

cleanup() {
  if [ "$CLEANED_UP" = "1" ]; then
    return 0
  fi
  CLEANED_UP="1"
  trap - INT TERM EXIT
  if [ -n "$PRODUCER_PID" ]; then
    kill "$PRODUCER_PID" >/dev/null 2>&1 || true
  fi
  if [ "$STREAM_ACTIVE" = "1" ]; then
    curl -sS -X POST "$BACKEND_URL/api/audio/stream/stop" >/dev/null 2>&1 || true
  fi
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

if ! command -v parec >/dev/null 2>&1 && ! command -v ffmpeg >/dev/null 2>&1; then
  fail_hard "parec/ffmpeg 都不存在，无法采集本机输出音频。"
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
  fail_hard "没有找到可用的系统声音 monitor；请设置 PULSE_SOURCE，或确认 pactl/PulseAudio/PipeWire 正常。"
fi

log "开始转发本机声音：source=$SOURCE volume=$VOLUME backend=$BACKEND_URL"
log "说明：这是用户态虚拟声卡转发，不是内核驱动；新打开的应用会跟随默认输出，已打开的应用会尽量自动迁移。"
log "说明：只使用 QSM 端持续 PCM 实时流播放器；不再使用分段上传模式。"
log "按 Ctrl+C 停止。"

run_stream_mode() {
  [ "$USE_STREAM" = "1" ] || fail_hard "QSM_AUDIO_USE_STREAM=0，实时串流已禁用。"
  if ! command -v nc >/dev/null 2>&1; then
    fail_hard "nc 不存在，无法连接 QSM PCM 实时流。"
  fi

  if command -v adb >/dev/null 2>&1; then
    adb forward "tcp:${HOST_STREAM_PORT}" "tcp:${STREAM_PORT}" >/dev/null 2>&1 || true
  fi

  START_BODY="{\"port\":${STREAM_PORT},\"volume\":${VOLUME},\"rate\":${STREAM_RATE},\"channels\":1}"
  if ! curl -fsS -X POST "$BACKEND_URL/api/audio/stream/start" -H 'Content-Type: application/json' --data "$START_BODY" >/dev/null; then
    fail_hard "外设实时音频流启动失败。请先运行 scripts/deploy_qsm_gateway.sh 部署新版 QSM 网关。"
  fi
  STREAM_ACTIVE="1"
  log "已启动低延迟 PCM 实时流：127.0.0.1:${HOST_STREAM_PORT} -> QSM:${STREAM_PORT}"
  if command -v parec >/dev/null 2>&1; then
    log "使用 parec 低延迟采集，减少分段上传造成的规律性断续。"
    parec --device="$SOURCE" \
      --format=s16le \
      --rate="$STREAM_RATE" \
      --channels=1 \
      --latency-msec="${QSM_AUDIO_LATENCY_MS:-40}" \
      | nc 127.0.0.1 "$HOST_STREAM_PORT"
  else
    log "parec 不存在，使用 ffmpeg 低缓冲采集。"
    ffmpeg -hide_banner -loglevel error \
      -fflags nobuffer -flags low_delay \
      -f pulse -i "$SOURCE" \
      -ac 1 -ar "$STREAM_RATE" -sample_fmt s16 \
      -flush_packets 1 -f s16le - | nc 127.0.0.1 "$HOST_STREAM_PORT"
  fi
  fail_soft "实时音频流已结束。"
}

run_stream_mode
