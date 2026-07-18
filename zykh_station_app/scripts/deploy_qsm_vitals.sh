#!/usr/bin/env sh
set -u

HOST_PORT="${QSM_VITALS_FORWARD_HOST_PORT:-18085}"
DEVICE_PORT="${QSM_VITALS_FORWARD_DEVICE_PORT:-8085}"
QSM_HOME="${QSM_HOME:-/userdata/zykh_app}"
VITALS_HOME="${QSM_VITALS_HOME:-/userdata/qsm-vitals}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/../qsm_gateway"

log() { printf '[qsm-vitals] %s\n' "$*"; }
fail() { printf '[qsm-vitals] FAIL: %s\n' "$*" >&2; exit 1; }

command -v adb >/dev/null 2>&1 || fail "未找到 adb"
adb get-state >/dev/null 2>&1 || fail "未检测到可用外设网关设备"
[ -f "$SOURCE_DIR/read_vitals_uart8.pl" ] || fail "缺少 UART 体征读取器"
[ -f "$SOURCE_DIR/vitals_gateway.pl" ] || fail "缺少体征会话网关"
[ -f "$SOURCE_DIR/start_vitals_gateway.sh" ] || fail "缺少体征网关启动脚本"

log "部署体征读取器和会话网关"
adb shell "mkdir -p '$QSM_HOME/scripts' '$VITALS_HOME/data' '$VITALS_HOME/logs'" >/dev/null \
  || fail "创建板端目录失败"
adb push "$SOURCE_DIR/read_vitals_uart8.pl" "$QSM_HOME/scripts/read_vitals_uart8.pl" >/dev/null \
  || fail "推送 UART 读取器失败"
adb push "$SOURCE_DIR/vitals_gateway.pl" "$VITALS_HOME/vitals_gateway.pl" >/dev/null \
  || fail "推送体征会话网关失败"
adb push "$SOURCE_DIR/start_vitals_gateway.sh" "$VITALS_HOME/start_vitals_gateway.sh" >/dev/null \
  || fail "推送启动脚本失败"
adb shell "chmod +x '$QSM_HOME/scripts/read_vitals_uart8.pl' '$VITALS_HOME/vitals_gateway.pl' '$VITALS_HOME/start_vitals_gateway.sh'; QSM_VITALS_HOME='$VITALS_HOME' QSM_VITALS_PORT='$DEVICE_PORT' sh '$VITALS_HOME/start_vitals_gateway.sh'" >/dev/null \
  || fail "启动板端体征会话网关失败"

adb forward "tcp:$HOST_PORT" "tcp:$DEVICE_PORT" >/dev/null 2>&1 \
  || fail "建立体征端口转发失败"
if command -v curl >/dev/null 2>&1 \
  && curl -fsS --max-time 3 "http://127.0.0.1:$HOST_PORT/api/vitals/session/status?session_id=health" >/dev/null; then
  log "体征会话网关已就绪：http://127.0.0.1:$HOST_PORT"
  exit 0
fi

fail "体征会话网关已启动，但本机暂时无法访问"
