#!/usr/bin/env sh
set -u

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
HOST_PORT="${QSM_FORWARD_HOST_PORT:-18080}"
DEVICE_PORT="${QSM_FORWARD_DEVICE_PORT:-8080}"
QSM_BASE_URL="${QSM_BASE_URL:-http://127.0.0.1:${HOST_PORT}}"
BACKEND_URL="${ZYKH_BACKEND_URL:-http://127.0.0.1:8000}"
LOCAL_CAMERA_DEVICE="${LOCAL_CAMERA_DEVICE:-auto}"

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
  if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
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
  else
    warn "未检测到外设网关设备；真实外设联调前请检查连接。"
  fi
else
  warn "未找到 adb 命令；真实外设联调前请安装连接工具。"
fi

check_http "外设网关状态" "${QSM_BASE_URL}/api/status" || true

if [ "$LOCAL_CAMERA_DEVICE" = "auto" ]; then
  if find /dev -maxdepth 1 -name 'video*' -print -quit 2>/dev/null | grep -q .; then
    ok "已检测到本机摄像头设备。"
  else
    warn "未检测到本机摄像头设备。"
  fi
elif [ "$LOCAL_CAMERA_DEVICE" = "0" ] || [ "$LOCAL_CAMERA_DEVICE" = "1" ] || [ "$LOCAL_CAMERA_DEVICE" = "2" ]; then
  DEVICE_PATH="/dev/video${LOCAL_CAMERA_DEVICE}"
  if [ -e "$DEVICE_PATH" ]; then
    ok "本机摄像头设备存在：$DEVICE_PATH"
  else
    warn "本机摄像头设备未检测到：$DEVICE_PATH"
  fi
elif [ -e "$LOCAL_CAMERA_DEVICE" ]; then
  ok "本机摄像头设备存在：$LOCAL_CAMERA_DEVICE"
else
  warn "本机摄像头设备未检测到：$LOCAL_CAMERA_DEVICE"
fi

check_http "后端 QSM 状态" "${BACKEND_URL}/api/qsm/status" || true
check_http "后端体征接口" "${BACKEND_URL}/api/qsm/vitals" || true
if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 3 -X POST "${BACKEND_URL}/api/vitals/read-all" >/dev/null 2>&1; then
  ok "后端体征读取动作可访问：${BACKEND_URL}/api/vitals/read-all"
else
  warn "后端体征读取动作暂不可访问：${BACKEND_URL}/api/vitals/read-all"
fi
check_http "后端能力接口" "${BACKEND_URL}/api/qsm/capabilities" || true
check_http "后端系统检查" "${BACKEND_URL}/api/device/check" || true

printf '\n检查完成。WARN 项不会中断脚本；真实联调前请优先确认外设网关状态、摄像头和后端系统检查。\n'
