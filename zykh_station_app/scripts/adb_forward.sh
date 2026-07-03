#!/usr/bin/env sh
set -u

HOST_PORT="${QSM_FORWARD_HOST_PORT:-18080}"
DEVICE_PORT="${QSM_FORWARD_DEVICE_PORT:-8080}"

info() {
  printf '%s\n' "$1"
}

warn_mock() {
  info "未完成外设网关端口转发；本机主应用仍可继续使用 QSM_MODE=mock。"
}

if ! command -v adb >/dev/null 2>&1; then
  info "未找到 adb 命令。"
  warn_mock
  exit 0
fi

DEVICES="$(adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" { print $1 }')"
if [ -z "$DEVICES" ]; then
  info "未检测到已连接的外设网关设备。"
  warn_mock
  exit 0
fi

DEVICE_COUNT="$(printf '%s\n' "$DEVICES" | wc -l | tr -d ' ')"
if [ "$DEVICE_COUNT" -gt 1 ]; then
  SERIAL="$(printf '%s\n' "$DEVICES" | head -n 1)"
  info "检测到多个设备，使用第一个设备：$SERIAL"
  ADB_PREFIX="adb -s $SERIAL"
else
  ADB_PREFIX="adb"
fi

info "正在建立端口转发：127.0.0.1:${HOST_PORT} -> 设备 tcp:${DEVICE_PORT}"
if $ADB_PREFIX forward "tcp:${HOST_PORT}" "tcp:${DEVICE_PORT}" >/dev/null 2>&1; then
  info "端口转发已建立。"
  info "后端 real 模式可使用：QSM_MODE=real QSM_BASE_URL=http://127.0.0.1:${HOST_PORT}"
  exit 0
fi

info "端口转发失败。"
warn_mock
exit 0
