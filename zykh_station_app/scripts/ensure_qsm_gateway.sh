#!/usr/bin/env sh
set -u

HOST_PORT="${QSM_FORWARD_HOST_PORT:-18080}"
DEVICE_PORT="${QSM_FORWARD_DEVICE_PORT:-8080}"
FACE_HOST_PORT="${QSM_FACE_FORWARD_HOST_PORT:-18081}"
FACE_DEVICE_PORT="${QSM_FACE_FORWARD_DEVICE_PORT:-8081}"
AUDIO_HOST_PORT="${QSM_AUDIO_CAPTURE_FORWARD_HOST_PORT:-18082}"
AUDIO_DEVICE_PORT="${QSM_AUDIO_CAPTURE_FORWARD_DEVICE_PORT:-8082}"
VITALS_HOST_PORT="${QSM_VITALS_FORWARD_HOST_PORT:-18085}"
VITALS_DEVICE_PORT="${QSM_VITALS_FORWARD_DEVICE_PORT:-8085}"
FINGERPRINT_HOST_PORT="${QSM_FINGERPRINT_FORWARD_HOST_PORT:-18086}"
FINGERPRINT_DEVICE_PORT="${QSM_FINGERPRINT_FORWARD_DEVICE_PORT:-8086}"
LOCAL_AI_HOST_PORT="${QSM_LOCAL_AI_FORWARD_HOST_PORT:-18083}"
LOCAL_AI_DEVICE_PORT="${QSM_LOCAL_AI_FORWARD_DEVICE_PORT:-8083}"
LOCAL_ASR_HOST_PORT="${QSM_LOCAL_ASR_FORWARD_HOST_PORT:-18084}"
LOCAL_ASR_DEVICE_PORT="${QSM_LOCAL_ASR_FORWARD_DEVICE_PORT:-6006}"
AUDIO_STREAM_HOST_PORT="${QSM_AUDIO_STREAM_HOST_PORT:-19001}"
AUDIO_STREAM_DEVICE_PORT="${QSM_AUDIO_STREAM_DEVICE_PORT:-19001}"
QSM_BASE_URL="${QSM_BASE_URL:-http://127.0.0.1:${HOST_PORT}}"
QSM_FACE_BASE_URL="${QSM_FACE_BASE_URL:-http://127.0.0.1:${FACE_HOST_PORT}}"
QSM_MIC_BASE_URL="${QSM_MIC_BASE_URL:-http://127.0.0.1:${AUDIO_HOST_PORT}}"
QSM_VITALS_BASE_URL="${QSM_VITALS_BASE_URL:-http://127.0.0.1:${VITALS_HOST_PORT}}"
QSM_FINGERPRINT_BASE_URL="${QSM_FINGERPRINT_BASE_URL:-http://127.0.0.1:${FINGERPRINT_HOST_PORT}}"
QSM_HOME="${QSM_HOME:-/userdata/zykh_app}"
QSM_FACE_HOME="${QSM_FACE_HOME:-/userdata/qsm-face}"
QSM_AUDIO_HOME="${QSM_AUDIO_HOME:-/userdata/qsm-audio}"
QSM_VITALS_HOME="${QSM_VITALS_HOME:-/userdata/qsm-vitals}"
QSM_FINGERPRINT_HOME="${QSM_FINGERPRINT_HOME:-/userdata/qsm-fingerprint}"
QSM_START_SCRIPT="${QSM_START_SCRIPT:-/userdata/zykh_app/scripts/start_station_gateway.sh}"
QSM_FALLBACK_START_SCRIPT="${QSM_FALLBACK_START_SCRIPT:-/userdata/zykh_app/scripts/start_zykh_server.sh}"
QSM_FACE_START_SCRIPT="${QSM_FACE_START_SCRIPT:-/userdata/qsm-face/start_face_gateway.sh}"
QSM_AUDIO_START_SCRIPT="${QSM_AUDIO_START_SCRIPT:-/userdata/qsm-audio/start_audio_capture_gateway.sh}"
QSM_VITALS_START_SCRIPT="${QSM_VITALS_START_SCRIPT:-/userdata/qsm-vitals/start_vitals_gateway.sh}"
QSM_FINGERPRINT_START_SCRIPT="${QSM_FINGERPRINT_START_SCRIPT:-/userdata/qsm-fingerprint/start_fingerprint_gateway.sh}"

log() {
  printf '[qsm] %s\n' "$*"
}

warn() {
  printf '[qsm] WARN: %s\n' "$*" >&2
}

gateway_ready() {
  command -v curl >/dev/null 2>&1 && curl -fsS --max-time 3 -X POST "$QSM_BASE_URL/api/audio/stream/stop" >/dev/null 2>&1
}

face_ready() {
  command -v curl >/dev/null 2>&1 && curl -fsS --max-time 5 "$QSM_FACE_BASE_URL/api/face/status" >/dev/null 2>&1
}

audio_ready() {
  command -v curl >/dev/null 2>&1 && curl -fsS --max-time 3 "$QSM_MIC_BASE_URL/api/audio/capture/status" >/dev/null 2>&1
}

fingerprint_ready() {
  command -v curl >/dev/null 2>&1 && curl -fsS --max-time 5 "$QSM_FINGERPRINT_BASE_URL/api/fingerprint/status" >/dev/null 2>&1
}

vitals_ready() {
  command -v curl >/dev/null 2>&1 && curl -fsS --max-time 3 "$QSM_VITALS_BASE_URL/api/vitals/session/status?session_id=health" >/dev/null 2>&1
}

local_asr_ready() {
  command -v nc >/dev/null 2>&1 && nc -z -w 1 127.0.0.1 "$LOCAL_ASR_HOST_PORT" >/dev/null 2>&1
}

if gateway_ready && face_ready && audio_ready && fingerprint_ready && vitals_ready && local_asr_ready; then
  log "外设网关已可访问：$QSM_BASE_URL"
  log "人脸识别网关已可访问：$QSM_FACE_BASE_URL"
  log "麦克风采集网关已可访问：$QSM_MIC_BASE_URL"
  log "指纹识别网关已可访问：$QSM_FINGERPRINT_BASE_URL"
  log "体征测量网关已可访问：$QSM_VITALS_BASE_URL"
  log "本地 Paraformer 语音识别已可访问：127.0.0.1:${LOCAL_ASR_HOST_PORT}"
  exit 0
fi

if ! command -v adb >/dev/null 2>&1; then
  warn "未找到 adb，无法自动检查外设网关；本机应用仍会继续启动。"
  exit 0
fi

DEVICES="$(adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" { print $1 }')"
if [ -z "$DEVICES" ]; then
  warn "未检测到外设网关设备；本机应用仍会继续启动。"
  exit 0
fi

DEVICE_COUNT="$(printf '%s\n' "$DEVICES" | wc -l | tr -d ' ')"
if [ "$DEVICE_COUNT" -gt 1 ]; then
  SERIAL="$(printf '%s\n' "$DEVICES" | head -n 1)"
  ADB_PREFIX="adb -s $SERIAL"
  warn "检测到多个设备，使用第一个设备：$SERIAL"
else
  ADB_PREFIX="adb"
fi

log "建立外设网关端口转发：127.0.0.1:${HOST_PORT} -> tcp:${DEVICE_PORT}"
$ADB_PREFIX forward "tcp:${HOST_PORT}" "tcp:${DEVICE_PORT}" >/dev/null 2>&1 || warn "端口转发失败。"
log "建立人脸识别端口转发：127.0.0.1:${FACE_HOST_PORT} -> tcp:${FACE_DEVICE_PORT}"
$ADB_PREFIX forward "tcp:${FACE_HOST_PORT}" "tcp:${FACE_DEVICE_PORT}" >/dev/null 2>&1 || warn "人脸识别端口转发失败。"
log "建立麦克风采集端口转发：127.0.0.1:${AUDIO_HOST_PORT} -> tcp:${AUDIO_DEVICE_PORT}"
$ADB_PREFIX forward "tcp:${AUDIO_HOST_PORT}" "tcp:${AUDIO_DEVICE_PORT}" >/dev/null 2>&1 || warn "麦克风采集端口转发失败。"
log "建立体征测量端口转发：127.0.0.1:${VITALS_HOST_PORT} -> tcp:${VITALS_DEVICE_PORT}"
$ADB_PREFIX forward "tcp:${VITALS_HOST_PORT}" "tcp:${VITALS_DEVICE_PORT}" >/dev/null 2>&1 || warn "体征测量端口转发失败。"
log "建立指纹识别端口转发：127.0.0.1:${FINGERPRINT_HOST_PORT} -> tcp:${FINGERPRINT_DEVICE_PORT}"
$ADB_PREFIX forward "tcp:${FINGERPRINT_HOST_PORT}" "tcp:${FINGERPRINT_DEVICE_PORT}" >/dev/null 2>&1 || warn "指纹识别端口转发失败。"
log "建立离线模型端口转发：127.0.0.1:${LOCAL_AI_HOST_PORT} -> tcp:${LOCAL_AI_DEVICE_PORT}"
$ADB_PREFIX forward "tcp:${LOCAL_AI_HOST_PORT}" "tcp:${LOCAL_AI_DEVICE_PORT}" >/dev/null 2>&1 || warn "离线模型端口转发失败。"
if $ADB_PREFIX shell 'test -x /userdata/zykh_app/scripts/start_asr_service.sh' >/dev/null 2>&1; then
  $ADB_PREFIX shell '/userdata/zykh_app/scripts/start_asr_service.sh start' >/dev/null 2>&1 \
    || warn "板端本地语音识别服务未能启动。"
else
  warn "板端尚未部署本地语音识别；联网时仍可使用云端识别。"
fi
if $ADB_PREFIX shell 'test -x /userdata/zykh_app/scripts/start_local_tts_server.sh' >/dev/null 2>&1; then
  $ADB_PREFIX shell 'sh /userdata/zykh_app/scripts/start_local_tts_server.sh' >/dev/null 2>&1 \
    || warn "板端常驻离线语音服务未能启动，将使用兼容回退。"
fi
log "建立本地 Paraformer 语音识别端口转发：127.0.0.1:${LOCAL_ASR_HOST_PORT} -> tcp:${LOCAL_ASR_DEVICE_PORT}"
$ADB_PREFIX forward "tcp:${LOCAL_ASR_HOST_PORT}" "tcp:${LOCAL_ASR_DEVICE_PORT}" >/dev/null 2>&1 || warn "本地语音识别端口转发失败。"
log "建立实时音频播放端口转发：127.0.0.1:${AUDIO_STREAM_HOST_PORT} -> tcp:${AUDIO_STREAM_DEVICE_PORT}"
$ADB_PREFIX forward "tcp:${AUDIO_STREAM_HOST_PORT}" "tcp:${AUDIO_STREAM_DEVICE_PORT}" >/dev/null 2>&1 || warn "实时音频播放端口转发失败。"

if gateway_ready && face_ready && audio_ready && fingerprint_ready && vitals_ready; then
  log "端口转发后全部外设网关均已可访问。"
  exit 0
fi

if ! vitals_ready; then
  log "尝试启动体征测量网关服务。"
  $ADB_PREFIX shell "if [ -x '$QSM_VITALS_START_SCRIPT' ]; then QSM_VITALS_HOME='$QSM_VITALS_HOME' QSM_VITALS_PORT='$VITALS_DEVICE_PORT' sh '$QSM_VITALS_START_SCRIPT'; else exit 1; fi" >/dev/null 2>&1 \
    || warn "体征测量网关尚未部署；可运行 scripts/deploy_qsm_gateway.sh 完成部署。"
fi

if ! gateway_ready; then
  log "尝试启动外设网关服务。"
  $ADB_PREFIX shell "mkdir -p '$QSM_HOME/data' '$QSM_HOME/scripts'; if [ -x '$QSM_START_SCRIPT' ]; then QSM_HOME='$QSM_HOME' PORT='$DEVICE_PORT' sh '$QSM_START_SCRIPT'; elif [ -x '$QSM_FALLBACK_START_SCRIPT' ]; then sh '$QSM_FALLBACK_START_SCRIPT'; elif [ -f '$QSM_HOME/server.pl' ]; then ZYKH_HOME='$QSM_HOME' PORT='$DEVICE_PORT' CAMERA_DEVICE='/dev/video23' perl '$QSM_HOME/server.pl' --daemon; else echo 'server.pl not found'; exit 1; fi" >/dev/null 2>&1 \
    || warn "外设网关启动命令执行失败，请检查板端 server.pl 是否已部署。"
fi

if ! face_ready; then
  log "尝试启动人脸识别网关服务。"
  $ADB_PREFIX shell "if [ -x '$QSM_FACE_START_SCRIPT' ]; then QSM_FACE_HOME='$QSM_FACE_HOME' QSM_FACE_GATEWAY_PORT='$FACE_DEVICE_PORT' sh '$QSM_FACE_START_SCRIPT'; else exit 1; fi" >/dev/null 2>&1 \
    || warn "人脸识别网关尚未部署；可运行 scripts/deploy_qsm_gateway.sh 完成部署。"
fi

if ! audio_ready; then
  log "尝试启动麦克风采集网关服务。"
  $ADB_PREFIX shell "if [ -x '$QSM_AUDIO_START_SCRIPT' ]; then QSM_AUDIO_HOME='$QSM_AUDIO_HOME' QSM_AUDIO_CAPTURE_PORT='$AUDIO_DEVICE_PORT' sh '$QSM_AUDIO_START_SCRIPT'; else exit 1; fi" >/dev/null 2>&1 \
    || warn "麦克风采集网关尚未部署；可运行 scripts/deploy_qsm_gateway.sh 完成部署。"
fi

if ! fingerprint_ready; then
  log "尝试启动指纹识别网关服务。"
  $ADB_PREFIX shell "if [ -x '$QSM_FINGERPRINT_START_SCRIPT' ]; then QSM_FINGERPRINT_HOME='$QSM_FINGERPRINT_HOME' QSM_FINGERPRINT_PORT='$FINGERPRINT_DEVICE_PORT' sh '$QSM_FINGERPRINT_START_SCRIPT'; else exit 1; fi" >/dev/null 2>&1 \
    || warn "指纹识别网关尚未部署；可运行 scripts/deploy_qsm_gateway.sh 完成部署。"
fi

sleep 1
if gateway_ready; then
  log "外设网关启动完成：$QSM_BASE_URL"
else
  warn "外设网关仍不可访问；本机应用会继续启动，真实外设功能可能不可用。"
fi
if face_ready; then
  log "人脸识别网关启动完成：$QSM_FACE_BASE_URL"
else
  warn "人脸识别网关仍不可访问；身份确认功能将显示真实不可用状态。"
fi
if audio_ready; then
  log "麦克风采集网关启动完成：$QSM_MIC_BASE_URL"
else
  warn "麦克风采集网关仍不可访问；语音输入将显示真实不可用状态。"
fi
if fingerprint_ready; then
  log "指纹识别网关启动完成：$QSM_FINGERPRINT_BASE_URL"
else
  warn "指纹识别网关仍不可访问；取药时可改用面部确认。"
fi
if vitals_ready; then
  log "体征测量网关启动完成：$QSM_VITALS_BASE_URL"
else
  warn "体征测量网关仍不可访问；身体状态测量会显示真实不可用状态。"
fi
