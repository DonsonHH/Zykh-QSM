#!/usr/bin/env sh
set -u

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
ADB_BIN="${ADB_BIN:-adb}"
RUNTIME_DIR="${QSM_LOCAL_AI_RUNTIME_DIR:-/userdata/zykh_station_app/local-ai}"
ASSET_DIR="${QSM_LOCAL_AI_ASSET_DIR:-/opt/zykh-local-ai}"
SERVER="${QSM_LOCAL_AI_SERVER:-$ASSET_DIR/llama-server}"
MODEL="${QSM_LOCAL_AI_MODEL_FILE:-$ASSET_DIR/models/Qwen3.5-0.8B-Q4_K_M.gguf}"
BOARD_STOP="$ROOT_DIR/qsm_gateway/stop_local_ai.sh"

log() {
  printf '[offline-ai] %s\n' "$*"
}

warn() {
  printf '[offline-ai] WARN: %s\n' "$*" >&2
}

if ! command -v "$ADB_BIN" >/dev/null 2>&1; then
  warn "未找到 adb，跳过板端模型清理。"
  exit 0
fi

if [ -z "${ADB_SERIAL:-}" ]; then
  DEVICES="$($ADB_BIN devices 2>/dev/null | awk 'NR > 1 && $2 == "device" {print $1}')"
  DEVICE_COUNT="$(printf '%s\n' "$DEVICES" | awk 'NF {count += 1} END {print count + 0}')"
  if [ "$DEVICE_COUNT" -eq 0 ]; then
    warn "未检测到 QSM，跳过板端模型清理。"
    exit 0
  fi
  if [ "$DEVICE_COUNT" -ne 1 ]; then
    warn "检测到多个 QSM，请设置 ADB_SERIAL 后再清理板端模型。"
    exit 0
  fi
  ADB_SERIAL="$DEVICES"
fi

adb_run() {
  "$ADB_BIN" -s "$ADB_SERIAL" "$@"
}

if [ ! -f "$BOARD_STOP" ]; then
  warn "未找到受控停止脚本：$BOARD_STOP"
  exit 1
fi

adb_run shell "mkdir -p '$RUNTIME_DIR'" >/dev/null 2>&1 || {
  warn "无法访问板端模型运行目录。"
  exit 1
}
adb_run push "$BOARD_STOP" "$RUNTIME_DIR/stop_local_ai.sh" >/dev/null 2>&1 || {
  warn "无法部署受控停止脚本。"
  exit 1
}
adb_run shell "chmod 755 '$RUNTIME_DIR/stop_local_ai.sh' && LOCAL_AI_RUNTIME_DIR='$RUNTIME_DIR' LOCAL_AI_ASSET_DIR='$ASSET_DIR' LOCAL_AI_SERVER='$SERVER' LOCAL_AI_MODEL_FILE='$MODEL' sh '$RUNTIME_DIR/stop_local_ai.sh'" >/dev/null 2>&1 || {
  warn "板端模型进程与受管 PID 不匹配，未执行停止。"
  exit 1
}

log "板端问询模型进程已清理，资源保留给离线语音。"
