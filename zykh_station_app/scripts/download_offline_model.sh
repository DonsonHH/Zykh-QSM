#!/usr/bin/env sh

set -eu

MODEL_REPO="${OFFLINE_AI_MODEL_REPO:-unsloth/Qwen3.5-0.8B-GGUF}"
MODEL_NAME="${OFFLINE_AI_MODEL_NAME:-Qwen3.5-0.8B-Q4_K_M.gguf}"
MODEL_SHA256="${OFFLINE_AI_MODEL_SHA256:-bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517}"
MODEL_SIZE="${OFFLINE_AI_MODEL_SIZE:-532517120}"
CACHE_ROOT="${OFFLINE_AI_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/zykh/models}"
MODEL_PATH="${OFFLINE_AI_MODEL_PATH:-$CACHE_ROOT/$MODEL_NAME}"
PARTIAL_PATH="$MODEL_PATH.partial"
MODEL_URL="${OFFLINE_AI_MODEL_URL:-https://huggingface.co/$MODEL_REPO/resolve/main/$MODEL_NAME}"

log() {
  printf '[offline-ai-download] %s\n' "$*"
}

command -v curl >/dev/null 2>&1 || {
  log "FAIL: 未找到 curl。"
  exit 1
}
command -v sha256sum >/dev/null 2>&1 || {
  log "FAIL: 未找到 sha256sum。"
  exit 1
}

mkdir -p "$(dirname "$MODEL_PATH")"

verify_model() {
  candidate="$1"
  [ -s "$candidate" ] || return 1
  actual_size="$(wc -c <"$candidate" | tr -d ' ')"
  [ "$actual_size" = "$MODEL_SIZE" ] || return 1
  printf '%s  %s\n' "$MODEL_SHA256" "$candidate" | sha256sum -c - >/dev/null 2>&1
}

if verify_model "$MODEL_PATH"; then
  log "模型已存在且校验通过：$MODEL_PATH"
  printf '%s\n' "$MODEL_PATH"
  exit 0
fi

if [ -e "$MODEL_PATH" ]; then
  log "移除校验失败的完整文件：$MODEL_PATH"
  rm -f "$MODEL_PATH"
fi

log "从 Hugging Face 下载 $MODEL_REPO/$MODEL_NAME"
if [ -n "${HF_TOKEN:-}" ]; then
  curl -L --fail --retry 4 --retry-delay 2 -C - \
    -H "Authorization: Bearer $HF_TOKEN" \
    -o "$PARTIAL_PATH" "$MODEL_URL"
else
  curl -L --fail --retry 4 --retry-delay 2 -C - \
    -o "$PARTIAL_PATH" "$MODEL_URL"
fi

if ! verify_model "$PARTIAL_PATH"; then
  log "FAIL: 模型大小或 SHA-256 校验失败，保留 partial 文件供断点续传。"
  exit 1
fi

mv "$PARTIAL_PATH" "$MODEL_PATH"
log "下载完成并通过 SHA-256 校验：$MODEL_PATH"
printf '%s\n' "$MODEL_PATH"
