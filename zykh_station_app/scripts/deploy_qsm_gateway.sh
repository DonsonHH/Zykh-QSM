#!/usr/bin/env sh
set -u

HOST_PORT="${QSM_FORWARD_HOST_PORT:-18080}"
DEVICE_PORT="${QSM_FORWARD_DEVICE_PORT:-8080}"
QSM_HOME="${QSM_HOME:-/userdata/zykh_app}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
LOCAL_SERVER="$REPO_ROOT/zykh_app/server.pl"
LOCAL_START="$REPO_ROOT/zykh_app/scripts/start_zykh_server.sh"

log() {
  printf '[qsm-deploy] %s\n' "$*"
}

fail() {
  printf '[qsm-deploy] FAIL: %s\n' "$*" >&2
  exit 1
}

[ -f "$LOCAL_SERVER" ] || fail "找不到本地网关文件：$LOCAL_SERVER"
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

log "部署 server.pl 到 $QSM_HOME"
$ADB_PREFIX shell "mkdir -p '$QSM_HOME/scripts' '$QSM_HOME/data'" >/dev/null || fail "创建板端目录失败"
$ADB_PREFIX push "$LOCAL_SERVER" "$QSM_HOME/server.pl" >/dev/null || fail "推送 server.pl 失败"
if [ -f "$LOCAL_START" ]; then
  $ADB_PREFIX push "$LOCAL_START" "$QSM_HOME/scripts/start_zykh_server.sh" >/dev/null || fail "推送启动脚本失败"
fi
$ADB_PREFIX shell "chmod +x '$QSM_HOME/scripts/start_zykh_server.sh' 2>/dev/null; for pid in \$(pgrep -f '$QSM_HOME/server.pl' 2>/dev/null); do [ \"\$pid\" = \"\$\$\" ] || kill \"\$pid\" 2>/dev/null || true; done; sleep 0.3; cd '$QSM_HOME' && ZYKH_HOME='$QSM_HOME' PORT='$DEVICE_PORT' perl '$QSM_HOME/server.pl' --daemon" >/dev/null \
  || fail "重启板端网关失败"

log "建立端口转发：127.0.0.1:$HOST_PORT -> tcp:$DEVICE_PORT"
$ADB_PREFIX forward "tcp:${HOST_PORT}" "tcp:${DEVICE_PORT}" >/dev/null 2>&1 || fail "端口转发失败"

if command -v curl >/dev/null 2>&1; then
  count=0
  while [ "$count" -lt 12 ]; do
    if curl -fsS --max-time 3 -X POST "http://127.0.0.1:${HOST_PORT}/api/audio/stream/stop" >/dev/null 2>&1; then
      log "部署完成，外设网关已可访问。"
      exit 0
    fi
    count=$((count + 1))
    sleep 0.5
  done
fi

fail "已部署并尝试启动，但本机暂时无法访问新版外设音频流接口。"
