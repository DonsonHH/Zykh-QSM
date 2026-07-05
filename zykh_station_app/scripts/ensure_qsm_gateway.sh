#!/usr/bin/env sh
set -u

HOST_PORT="${QSM_FORWARD_HOST_PORT:-18080}"
DEVICE_PORT="${QSM_FORWARD_DEVICE_PORT:-8080}"
QSM_BASE_URL="${QSM_BASE_URL:-http://127.0.0.1:${HOST_PORT}}"
QSM_HOME="${QSM_HOME:-/userdata/zykh_app}"
QSM_START_SCRIPT="${QSM_START_SCRIPT:-/userdata/zykh_app/scripts/start_zykh_server.sh}"

log() {
  printf '[qsm] %s\n' "$*"
}

warn() {
  printf '[qsm] WARN: %s\n' "$*" >&2
}

gateway_ready() {
  command -v curl >/dev/null 2>&1 && curl -fsS --max-time 16 "$QSM_BASE_URL/api/status" >/dev/null 2>&1
}

if gateway_ready; then
  log "外设网关已可访问：$QSM_BASE_URL"
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

if gateway_ready; then
  log "端口转发后外设网关已可访问。"
  exit 0
fi

log "尝试启动外设网关服务。"
$ADB_PREFIX shell "mkdir -p '$QSM_HOME/data' '$QSM_HOME/scripts'; if [ -x '$QSM_START_SCRIPT' ]; then sh '$QSM_START_SCRIPT'; elif [ -f '$QSM_HOME/server.pl' ]; then ZYKH_HOME='$QSM_HOME' PORT='$DEVICE_PORT' perl '$QSM_HOME/server.pl' --daemon; else echo 'server.pl not found'; exit 1; fi" >/dev/null 2>&1 \
  || warn "外设网关启动命令执行失败，请检查板端 server.pl 是否已部署。"

sleep 1
if gateway_ready; then
  log "外设网关启动完成：$QSM_BASE_URL"
else
  warn "外设网关仍不可访问；本机应用会继续启动，真实外设功能可能不可用。"
fi
