#!/usr/bin/env sh

set -u

HOST_PORT="${QSM_LOCAL_AI_FORWARD_HOST_PORT:-18083}"
DEVICE_PORT="${QSM_LOCAL_AI_FORWARD_DEVICE_PORT:-8083}"
BASE_URL="${LOCAL_AI_BASE_URL:-http://127.0.0.1:${HOST_PORT}}"
RUNTIME_DIR="${QSM_LOCAL_AI_RUNTIME_DIR:-/userdata/zykh_station_app/local-ai}"
START_SCRIPT="$RUNTIME_DIR/start_local_ai.sh"
START_TIMEOUT="${LOCAL_AI_START_TIMEOUT:-70}"

log() {
  printf '[offline-ai] %s\n' "$*"
}

warn() {
  printf '[offline-ai] WARN: %s\n' "$*" >&2
}

ready() {
  command -v curl >/dev/null 2>&1 \
    && curl -fsS --max-time 2 "$BASE_URL/health" 2>/dev/null \
      | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"'
}

if ready; then
  log "QSM 离线模型已就绪：$BASE_URL"
  exit 0
fi

if ! command -v adb >/dev/null 2>&1; then
  warn "未找到 adb，无法启动 QSM 离线模型。"
  exit 1
fi

DEVICES="$(adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" { print $1 }')"
if [ -z "$DEVICES" ]; then
  warn "未检测到 QSM，无法启动离线模型。"
  exit 1
fi

DEVICE_COUNT="$(printf '%s\n' "$DEVICES" | wc -l | tr -d ' ')"
if [ "$DEVICE_COUNT" -gt 1 ]; then
  SERIAL="$(printf '%s\n' "$DEVICES" | head -n 1)"
  ADB_PREFIX="adb -s $SERIAL"
  warn "检测到多个设备，使用第一个设备：$SERIAL"
else
  ADB_PREFIX="adb"
fi

$ADB_PREFIX forward "tcp:${HOST_PORT}" "tcp:${DEVICE_PORT}" >/dev/null 2>&1 || {
  warn "离线模型端口转发失败。"
  exit 1
}

if ready; then
  log "端口转发后 QSM 离线模型已就绪。"
  exit 0
fi

if ! $ADB_PREFIX shell "test -x '$START_SCRIPT'" >/dev/null 2>&1; then
  warn "板端尚未部署离线模型；请先运行 scripts/deploy_offline_ai.sh。"
  exit 1
fi

log "启动 QSM 离线模型，首次载入通常需要 15-30 秒。"
$ADB_PREFIX shell "LOCAL_AI_PORT='$DEVICE_PORT' LOCAL_AI_START_TIMEOUT='$START_TIMEOUT' sh '$START_SCRIPT'" \
  || {
    warn "板端离线模型启动失败。"
    exit 1
  }

WAITED=0
while [ "$WAITED" -lt "$START_TIMEOUT" ]; do
  if ready; then
    log "QSM 离线模型启动完成：$BASE_URL"
    exit 0
  fi
  WAITED=$((WAITED + 1))
  sleep 1
done

warn "离线模型未在 ${START_TIMEOUT}s 内就绪。"
exit 1
