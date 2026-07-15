#!/usr/bin/env sh

set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$ROOT_DIR/.." && pwd)"
CACHE_ROOT="${OFFLINE_AI_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/zykh/models}"
MODEL_NAME="${OFFLINE_AI_MODEL_NAME:-Qwen3.5-0.8B-Q4_K_M.gguf}"
MODEL_SHA256="${OFFLINE_AI_MODEL_SHA256:-bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517}"
MODEL_PATH="${OFFLINE_AI_MODEL_PATH:-$CACHE_ROOT/$MODEL_NAME}"
ENGINE_SHA256="${OFFLINE_AI_ENGINE_SHA256:-683752e7bb06850a1ebed20d001203549dc588b234b89c5ba264da573d17a9d0}"
ENGINE_CACHE="$CACHE_ROOT/llama-server"
ENGINE_PATH="${LLAMA_SERVER_BIN:-}"
ASSET_DIR="${QSM_LOCAL_AI_ASSET_DIR:-/opt/zykh-local-ai}"
RUNTIME_DIR="${QSM_LOCAL_AI_RUNTIME_DIR:-/userdata/zykh_station_app/local-ai}"
DEVICE_PORT="${QSM_LOCAL_AI_FORWARD_DEVICE_PORT:-8083}"
HOST_PORT="${QSM_LOCAL_AI_FORWARD_HOST_PORT:-18083}"
ARCHIVE="${OFFLINE_AI_EXAMPLE_ARCHIVE:-$REPO_ROOT/智药康护-新开发板一键部署包(1).zip}"
ROOT_REMOUNTED=0

log() {
  printf '[offline-ai-deploy] %s\n' "$*"
}

fail() {
  printf '[offline-ai-deploy] FAIL: %s\n' "$*" >&2
  exit 1
}

restore_root_readonly() {
  if [ "$ROOT_REMOUNTED" = "1" ]; then
    $ADB_PREFIX shell "sync; mount -o remount,ro /" >/dev/null 2>&1 || true
    ROOT_REMOUNTED=0
  fi
}

trap restore_root_readonly EXIT
trap 'restore_root_readonly; exit 129' HUP
trap 'restore_root_readonly; exit 130' INT
trap 'restore_root_readonly; exit 143' TERM

command -v adb >/dev/null 2>&1 || fail "未找到 adb。"
command -v sha256sum >/dev/null 2>&1 || fail "未找到 sha256sum。"

if [ ! -s "$MODEL_PATH" ]; then
  log "本机缓存中没有模型，先执行 Hugging Face 下载。"
  sh "$ROOT_DIR/scripts/download_offline_model.sh" >/dev/null
fi
printf '%s  %s\n' "$MODEL_SHA256" "$MODEL_PATH" | sha256sum -c - >/dev/null \
  || fail "模型 SHA-256 校验失败：$MODEL_PATH"

if [ -z "$ENGINE_PATH" ] && [ -x "$ENGINE_CACHE" ]; then
  ENGINE_PATH="$ENGINE_CACHE"
fi
if [ -z "$ENGINE_PATH" ] && [ -x "/tmp/zykh-offline-bundle/payload/llama-server" ]; then
  ENGINE_PATH="/tmp/zykh-offline-bundle/payload/llama-server"
fi
if [ -z "$ENGINE_PATH" ] && [ -f "$ARCHIVE" ]; then
  command -v unzip >/dev/null 2>&1 || fail "需要 unzip 从示例包提取 llama-server。"
  mkdir -p "$CACHE_ROOT"
  unzip -p "$ARCHIVE" 'payload/llama-server' >"$ENGINE_CACHE" \
    || fail "无法从示例包提取 payload/llama-server。"
  chmod 755 "$ENGINE_CACHE"
  ENGINE_PATH="$ENGINE_CACHE"
fi
[ -n "$ENGINE_PATH" ] && [ -x "$ENGINE_PATH" ] \
  || fail "找不到 llama-server；请设置 LLAMA_SERVER_BIN。"
printf '%s  %s\n' "$ENGINE_SHA256" "$ENGINE_PATH" | sha256sum -c - >/dev/null \
  || fail "llama-server SHA-256 校验失败：$ENGINE_PATH"

DEVICES="$(adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" { print $1 }')"
[ -n "$DEVICES" ] || fail "未检测到 QSM。"
DEVICE_COUNT="$(printf '%s\n' "$DEVICES" | wc -l | tr -d ' ')"
if [ "$DEVICE_COUNT" -gt 1 ]; then
  SERIAL="$(printf '%s\n' "$DEVICES" | head -n 1)"
  ADB_PREFIX="adb -s $SERIAL"
  log "检测到多个设备，使用第一个设备：$SERIAL"
else
  ADB_PREFIX="adb"
fi

log "验证板端架构和 llama.cpp 引擎。"
$ADB_PREFIX push "$ENGINE_PATH" /tmp/zykh-llama-server-check >/dev/null
$ADB_PREFIX shell "chmod 755 /tmp/zykh-llama-server-check; /tmp/zykh-llama-server-check --version" \
  || fail "llama-server 无法在 QSM 上运行。"

REMOTE_MODEL="$ASSET_DIR/models/$MODEL_NAME"
REMOTE_ENGINE="$ASSET_DIR/llama-server"
REMOTE_MODEL_HASH="$($ADB_PREFIX shell "sha256sum '$REMOTE_MODEL' 2>/dev/null" | awk '{print $1}' | tr -d '\r' || true)"
REMOTE_ENGINE_HASH="$($ADB_PREFIX shell "sha256sum '$REMOTE_ENGINE' 2>/dev/null" | awk '{print $1}' | tr -d '\r' || true)"

if [ "$REMOTE_MODEL_HASH" != "$MODEL_SHA256" ] || [ "$REMOTE_ENGINE_HASH" != "$ENGINE_SHA256" ]; then
  log "临时重挂根分区为可写并部署模型资产。"
  $ADB_PREFIX shell "mount -o remount,rw /; mkdir -p '$ASSET_DIR/models'" \
    || fail "无法将 QSM 根分区临时重挂为可写。"
  ROOT_REMOUNTED=1

  if [ "$REMOTE_ENGINE_HASH" != "$ENGINE_SHA256" ]; then
    $ADB_PREFIX push "$ENGINE_PATH" "$REMOTE_ENGINE.partial" >/dev/null \
      || fail "推送 llama-server 失败。"
    $ADB_PREFIX shell "chmod 755 '$REMOTE_ENGINE.partial'; mv '$REMOTE_ENGINE.partial' '$REMOTE_ENGINE'" \
      || fail "安装 llama-server 失败。"
  fi

  if [ "$REMOTE_MODEL_HASH" != "$MODEL_SHA256" ]; then
    PUSHED_HASH="$($ADB_PREFIX shell "sha256sum '$REMOTE_MODEL.partial' 2>/dev/null" | awk '{print $1}' | tr -d '\r' || true)"
    if [ "$PUSHED_HASH" = "$MODEL_SHA256" ]; then
      log "发现已完整校验的 partial 模型，直接完成安装。"
    else
      log "推送 508MiB GGUF；根据 USB 速度通常需要 20-150 秒。"
      $ADB_PREFIX push "$MODEL_PATH" "$REMOTE_MODEL.partial" \
        || fail "推送 GGUF 模型失败。"
      PUSHED_HASH="$($ADB_PREFIX shell "sha256sum '$REMOTE_MODEL.partial'" | awk '{print $1}' | tr -d '\r')"
    fi
    [ "$PUSHED_HASH" = "$MODEL_SHA256" ] || fail "板端模型 SHA-256 校验失败。"
    $ADB_PREFIX shell "mv '$REMOTE_MODEL.partial' '$REMOTE_MODEL'" \
      || fail "安装 GGUF 模型失败。"
  fi

  restore_root_readonly
else
  log "板端模型与引擎已存在且 SHA-256 正确，跳过大文件推送。"
fi

log "部署项目自有的离线模型控制脚本。"
$ADB_PREFIX shell "mkdir -p '$RUNTIME_DIR'" >/dev/null
for script in start_local_ai.sh stop_local_ai.sh status_local_ai.sh; do
  $ADB_PREFIX push "$ROOT_DIR/qsm_gateway/$script" "$RUNTIME_DIR/$script" >/dev/null \
    || fail "推送 $script 失败。"
done
$ADB_PREFIX shell "chmod 755 '$RUNTIME_DIR/'*.sh" >/dev/null

$ADB_PREFIX forward "tcp:${HOST_PORT}" "tcp:${DEVICE_PORT}" >/dev/null \
  || fail "离线模型端口转发失败。"

log "启动 QSM 离线模型。"
$ADB_PREFIX shell "LOCAL_AI_ASSET_DIR='$ASSET_DIR' LOCAL_AI_RUNTIME_DIR='$RUNTIME_DIR' LOCAL_AI_PORT='$DEVICE_PORT' sh '$RUNTIME_DIR/start_local_ai.sh'" \
  || fail "QSM 离线模型启动失败。"

HEALTH="$(curl -fsS --max-time 5 "http://127.0.0.1:${HOST_PORT}/health" 2>/dev/null || true)"
printf '%s' "$HEALTH" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"' \
  || fail "模型进程已启动，但本机健康检查未通过：$HEALTH"

SMOKE_RESPONSE="$(curl -fsS --max-time 120 \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen3.5-0.8B-Q4_K_M","messages":[{"role":"system","content":"你是离线健康信息整理助手，只做风险提示，不做诊断或处方。请用一句中文回答。"},{"role":"user","content":"我有轻微头晕，应该先补充哪些信息？"}],"temperature":0.1,"max_tokens":80,"stream":false}' \
  "http://127.0.0.1:${HOST_PORT}/v1/chat/completions" 2>/dev/null || true)"
printf '%s' "$SMOKE_RESPONSE" | grep -q '"choices"' \
  || fail "离线推理 smoke 未返回 choices：$SMOKE_RESPONSE"

log "部署完成：QSM 本地模型、健康检查和真实推理均已通过。"
printf '%s\n' "$SMOKE_RESPONSE"
