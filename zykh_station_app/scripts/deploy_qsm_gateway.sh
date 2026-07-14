#!/usr/bin/env sh
set -u

HOST_PORT="${QSM_FORWARD_HOST_PORT:-18080}"
DEVICE_PORT="${QSM_FORWARD_DEVICE_PORT:-8080}"
QSM_HOME="${QSM_HOME:-/userdata/zykh_app}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
LOCAL_START="$REPO_ROOT/zykh_station_app/qsm_gateway/start_station_gateway.sh"
LOCAL_VITALS_UART="$REPO_ROOT/zykh_station_app/qsm_gateway/read_vitals_uart8.pl"

log() {
  printf '[qsm-deploy] %s\n' "$*"
}

fail() {
  printf '[qsm-deploy] FAIL: %s\n' "$*" >&2
  exit 1
}

[ -f "$LOCAL_START" ] || fail "找不到外设网关启动脚本：$LOCAL_START"
[ -f "$LOCAL_VITALS_UART" ] || fail "找不到 UART8 体征读取器：$LOCAL_VITALS_UART"
command -v adb >/dev/null 2>&1 || fail "未找到 adb"

DEVICES="$(adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" { print $1 }')"
[ -n "$DEVICES" ] || fail "未检测到 QSM 设备"

DEVICE_COUNT="$(printf '%s\n' "$DEVICES" | wc -l | tr -d ' ')"
if [ "$DEVICE_COUNT" -gt 1 ]; then
  SERIAL="$(printf '%s\n' "$DEVICES" | head -n 1)"
  ADB_PREFIX="adb -s $SERIAL"
  log "检测到多个设备，使用第一个设备：$SERIAL"
else
  ADB_PREFIX="adb"
fi

log "部署 UART8 体征适配到现有外设网关"
$ADB_PREFIX shell "mkdir -p '$QSM_HOME/scripts' '$QSM_HOME/data'" >/dev/null || fail "创建板端目录失败"
$ADB_PREFIX shell "test -f '$QSM_HOME/server.pl'" >/dev/null 2>&1 \
  || fail "板端缺少 $QSM_HOME/server.pl；请先部署外设网关，再安装 UART8 适配。"
$ADB_PREFIX push "$LOCAL_START" "$QSM_HOME/scripts/start_station_gateway.sh" >/dev/null || fail "推送外设网关启动脚本失败"
$ADB_PREFIX push "$LOCAL_VITALS_UART" "$QSM_HOME/scripts/read_vitals_uart8.pl" >/dev/null || fail "推送 UART8 体征读取器失败"
$ADB_PREFIX shell "chmod +x '$QSM_HOME/scripts/start_station_gateway.sh' '$QSM_HOME/scripts/read_vitals_uart8.pl'; QSM_HOME='$QSM_HOME' PORT='$DEVICE_PORT' sh '$QSM_HOME/scripts/start_station_gateway.sh'" >/dev/null \
  || fail "重启板端网关失败"

log "建立端口转发：127.0.0.1:$HOST_PORT -> tcp:$DEVICE_PORT"
$ADB_PREFIX forward "tcp:${HOST_PORT}" "tcp:${DEVICE_PORT}" >/dev/null 2>&1 || fail "端口转发失败"

command -v curl >/dev/null 2>&1 || fail "未找到 curl，无法完成真实体征验收。"
count=0
while [ "$count" -lt 12 ]; do
  if curl -fsS --max-time 3 -X POST "http://127.0.0.1:${HOST_PORT}/api/audio/stream/stop" >/dev/null 2>&1; then
    break
  fi
  count=$((count + 1))
  sleep 0.5
done
[ "$count" -lt 12 ] || fail "已部署并尝试启动，但本机暂时无法访问外设网关。"

log "读取一次 UART8 综合体征，未放手指时出现 awaiting_finger 也表示硬件链路已响应。"
VITALS_RESPONSE="$(curl -fsS --max-time 25 -X POST "http://127.0.0.1:${HOST_PORT}/api/vitals/read_all" 2>/dev/null)" \
  || fail "外设网关可访问，但综合体征接口读取失败。"
case "$VITALS_RESPONSE" in
  *UART8-vitals-24B*)
    log "部署完成：外设网关与 UART8 体征模块均已响应。"
    ;;
  *)
    fail "综合体征接口未返回 UART8-vitals-24B 标识，请检查板端启动环境。"
    ;;
esac
