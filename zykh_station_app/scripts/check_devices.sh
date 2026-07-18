#!/usr/bin/env sh
set -u

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
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
QSM_BASE_URL="${QSM_BASE_URL:-http://127.0.0.1:${HOST_PORT}}"
QSM_FACE_BASE_URL="${QSM_FACE_BASE_URL:-http://127.0.0.1:${FACE_HOST_PORT}}"
QSM_MIC_BASE_URL="${QSM_MIC_BASE_URL:-http://127.0.0.1:${AUDIO_HOST_PORT}}"
QSM_VITALS_BASE_URL="${QSM_VITALS_BASE_URL:-http://127.0.0.1:${VITALS_HOST_PORT}}"
QSM_FINGERPRINT_BASE_URL="${QSM_FINGERPRINT_BASE_URL:-http://127.0.0.1:${FINGERPRINT_HOST_PORT}}"
LOCAL_AI_BASE_URL="${LOCAL_AI_BASE_URL:-http://127.0.0.1:${LOCAL_AI_HOST_PORT}}"
BACKEND_URL="${ZYKH_BACKEND_URL:-http://127.0.0.1:8000}"

ok() {
  printf 'OK   %s\n' "$1"
}

warn() {
  printf 'WARN %s\n' "$1"
}

fail() {
  printf 'FAIL %s\n' "$1"
}

check_http() {
  label="$1"
  url="$2"
  timeout_seconds="${3:-5}"
  if command -v curl >/dev/null 2>&1 && curl -fsS --max-time "$timeout_seconds" "$url" >/dev/null 2>&1; then
    ok "$label 可访问：$url"
    return 0
  fi
  warn "$label 暂不可访问：$url"
  return 1
}

printf '智药康护终端设备检查\n'
printf '工作目录：%s\n\n' "$ROOT_DIR"

if command -v adb >/dev/null 2>&1; then
  ok "已找到 adb 命令。"
  DEVICES="$(adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" { print $1 }')"
  if [ -n "$DEVICES" ]; then
    ok "已检测到外设网关设备。"
    SERIAL="$(printf '%s\n' "$DEVICES" | head -n 1)"
    DEVICE_COUNT="$(printf '%s\n' "$DEVICES" | wc -l | tr -d ' ')"
    if [ "$DEVICE_COUNT" -gt 1 ]; then
      warn "检测到多个设备，使用第一个设备：$SERIAL"
      ADB_PREFIX="adb -s $SERIAL"
    else
      ADB_PREFIX="adb"
    fi
    if $ADB_PREFIX forward "tcp:${HOST_PORT}" "tcp:${DEVICE_PORT}" >/dev/null 2>&1; then
      ok "端口转发已建立：127.0.0.1:${HOST_PORT} -> tcp:${DEVICE_PORT}"
    else
      warn "端口转发未建立；真实外设联调前请检查连接和网关服务。"
    fi
    if $ADB_PREFIX forward "tcp:${FACE_HOST_PORT}" "tcp:${FACE_DEVICE_PORT}" >/dev/null 2>&1; then
      ok "人脸服务转发已建立：127.0.0.1:${FACE_HOST_PORT} -> tcp:${FACE_DEVICE_PORT}"
    else
      warn "人脸服务转发未建立；请检查板端人脸网关。"
    fi
    if $ADB_PREFIX forward "tcp:${AUDIO_HOST_PORT}" "tcp:${AUDIO_DEVICE_PORT}" >/dev/null 2>&1; then
      ok "麦克风服务转发已建立：127.0.0.1:${AUDIO_HOST_PORT} -> tcp:${AUDIO_DEVICE_PORT}"
    else
      warn "麦克风服务转发未建立；请检查板端音频采集网关。"
    fi
    if $ADB_PREFIX forward "tcp:${VITALS_HOST_PORT}" "tcp:${VITALS_DEVICE_PORT}" >/dev/null 2>&1; then
      ok "体征服务转发已建立：127.0.0.1:${VITALS_HOST_PORT} -> tcp:${VITALS_DEVICE_PORT}"
    else
      warn "体征服务转发未建立；请检查板端体征会话网关。"
    fi
    if $ADB_PREFIX forward "tcp:${FINGERPRINT_HOST_PORT}" "tcp:${FINGERPRINT_DEVICE_PORT}" >/dev/null 2>&1; then
      ok "指纹服务转发已建立：127.0.0.1:${FINGERPRINT_HOST_PORT} -> tcp:${FINGERPRINT_DEVICE_PORT}"
    else
      warn "指纹服务转发未建立；取药时仍可改用面部确认。"
    fi
    if $ADB_PREFIX forward "tcp:${LOCAL_AI_HOST_PORT}" "tcp:${LOCAL_AI_DEVICE_PORT}" >/dev/null 2>&1; then
      ok "离线模型转发已建立：127.0.0.1:${LOCAL_AI_HOST_PORT} -> tcp:${LOCAL_AI_DEVICE_PORT}"
    else
      warn "离线模型转发未建立；请检查板端模型服务。"
    fi
  else
    warn "未检测到外设网关设备；真实外设联调前请检查连接。"
  fi
else
  warn "未找到 adb 命令；真实外设联调前请安装连接工具。"
fi

check_http "外设网关状态" "${QSM_BASE_URL}/api/status" 8 || true
check_http "人脸识别网关" "${QSM_FACE_BASE_URL}/api/face/status" 15 || true
check_http "FF Camera 麦克风" "${QSM_MIC_BASE_URL}/api/audio/capture/status" 8 || true
check_http "QSM 体征会话网关" "${QSM_VITALS_BASE_URL}/api/vitals/session/status?session_id=health" 5 || true
check_http "AS608 指纹模块" "${QSM_FINGERPRINT_BASE_URL}/api/fingerprint/status" 10 || true
check_http "QSM 离线模型" "${LOCAL_AI_BASE_URL}/health" 5 || true

if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 12 -X POST "${QSM_BASE_URL}/api/camera/capture" >/dev/null 2>&1; then
  ok "外设摄像头可抓取真实画面。"
else
  warn "外设摄像头暂时无法抓取画面。"
fi

check_http "后端 QSM 状态" "${BACKEND_URL}/api/qsm/status" 10 || true
check_http "后端体征接口" "${BACKEND_URL}/api/qsm/vitals" 35 || true
if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 35 -X POST "${BACKEND_URL}/api/vitals/read-all" >/dev/null 2>&1; then
  ok "后端体征读取动作可访问：${BACKEND_URL}/api/vitals/read-all"
else
  warn "后端体征读取动作暂不可访问：${BACKEND_URL}/api/vitals/read-all"
fi
check_http "后端能力接口" "${BACKEND_URL}/api/qsm/capabilities" 10 || true
check_http "后端身份接口" "${BACKEND_URL}/api/identity/status" 15 || true
check_http "后端指纹接口" "${BACKEND_URL}/api/fingerprint/status" 15 || true
check_http "后端麦克风接口" "${BACKEND_URL}/api/audio/host/status" 8 || true
check_http "后端系统检查" "${BACKEND_URL}/api/device/check" 45 || true

printf '\n检查完成。WARN 项不会中断脚本；真实联调前请优先确认外设网关状态、摄像头、麦克风和后端系统检查。\n'
