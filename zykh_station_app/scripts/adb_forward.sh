#!/usr/bin/env sh
set -u

HOST_PORT="${QSM_FORWARD_HOST_PORT:-18080}"
DEVICE_PORT="${QSM_FORWARD_DEVICE_PORT:-8080}"
FACE_HOST_PORT="${QSM_FACE_FORWARD_HOST_PORT:-18081}"
FACE_DEVICE_PORT="${QSM_FACE_FORWARD_DEVICE_PORT:-8081}"
AUDIO_HOST_PORT="${QSM_AUDIO_CAPTURE_FORWARD_HOST_PORT:-18082}"
AUDIO_DEVICE_PORT="${QSM_AUDIO_CAPTURE_FORWARD_DEVICE_PORT:-8082}"
LOCAL_AI_HOST_PORT="${QSM_LOCAL_AI_FORWARD_HOST_PORT:-18083}"
LOCAL_AI_DEVICE_PORT="${QSM_LOCAL_AI_FORWARD_DEVICE_PORT:-8083}"

info() {
  printf '%s\n' "$1"
}

ok() {
  info "OK   $1"
}

warn() {
  info "WARN $1"
}

fail() {
  info "FAIL $1"
}

warn_real() {
  warn "未完成外设网关端口转发；真实外设联调前请检查连接和网关服务。"
}

if ! command -v adb >/dev/null 2>&1; then
  fail "未找到 adb 命令。"
  warn_real
  exit 0
fi
ok "已找到 adb 命令。"

DEVICES="$(adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" { print $1 }')"
if [ -z "$DEVICES" ]; then
  warn "未检测到已连接的外设网关设备。"
  warn_real
  exit 0
fi

DEVICE_COUNT="$(printf '%s\n' "$DEVICES" | wc -l | tr -d ' ')"
if [ "$DEVICE_COUNT" -gt 1 ]; then
  SERIAL="$(printf '%s\n' "$DEVICES" | head -n 1)"
  warn "检测到多个设备，使用第一个设备：$SERIAL"
  ADB_PREFIX="adb -s $SERIAL"
else
  ADB_PREFIX="adb"
fi
ok "已检测到外设网关设备。"

info "正在建立端口转发：127.0.0.1:${HOST_PORT} -> 设备 tcp:${DEVICE_PORT}"
if $ADB_PREFIX forward "tcp:${HOST_PORT}" "tcp:${DEVICE_PORT}" >/dev/null 2>&1; then
  ok "端口转发已建立。"
  if $ADB_PREFIX forward "tcp:${FACE_HOST_PORT}" "tcp:${FACE_DEVICE_PORT}" >/dev/null 2>&1; then
    ok "人脸识别端口转发已建立：127.0.0.1:${FACE_HOST_PORT}。"
  else
    warn "人脸识别端口转发失败，主外设网关仍可继续使用。"
  fi
  if $ADB_PREFIX forward "tcp:${AUDIO_HOST_PORT}" "tcp:${AUDIO_DEVICE_PORT}" >/dev/null 2>&1; then
    ok "麦克风采集端口转发已建立：127.0.0.1:${AUDIO_HOST_PORT}。"
  else
    warn "麦克风采集端口转发失败，其他外设仍可继续使用。"
  fi
  if $ADB_PREFIX forward "tcp:${LOCAL_AI_HOST_PORT}" "tcp:${LOCAL_AI_DEVICE_PORT}" >/dev/null 2>&1; then
    ok "离线模型端口转发已建立：127.0.0.1:${LOCAL_AI_HOST_PORT}。"
  else
    warn "离线模型端口转发失败，云端与安全规则仍可继续使用。"
  fi
  info "后端 real 模式可使用：QSM_MODE=real QSM_BASE_URL=http://127.0.0.1:${HOST_PORT}"
  exit 0
fi

fail "端口转发失败。"
warn_real
exit 0
