#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ARCHIVE="${1:-$ROOT_DIR/../智药康护-QSM368ZP离线TTS部署包(1).zip}"
MODEL_ROOT="${HOST_OFFLINE_TTS_MODEL_ROOT:-$ROOT_DIR/data/host_tts}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/backend/.venv/bin/python}"

log() {
  printf '[host-offline-tts] %s\n' "$*"
}

fail() {
  printf '[host-offline-tts] FAIL: %s\n' "$*" >&2
  exit 1
}

command -v unzip >/dev/null 2>&1 || fail "未找到 unzip。"
[ -x "$PYTHON_BIN" ] || fail "未找到 Python 虚拟环境：$PYTHON_BIN"
[ -f "$ARCHIVE" ] || fail "未找到离线 TTS 部署包：$ARCHIVE"

log "安装主机 Sherpa-ONNX 运行时。"
"$PYTHON_BIN" -m pip install 'sherpa-onnx==1.13.4' 'numpy<2'

MODEL_DIR="$MODEL_ROOT/models/tts"
mkdir -p "$MODEL_DIR"
for entry in \
  zh_CN-xiao_ya-medium.onnx \
  zh_CN-xiao_ya-medium.onnx.json \
  lexicon.txt \
  tokens.txt \
  phone.fst \
  date.fst \
  number.fst; do
  log "提取模型文件：$entry"
  unzip -p "$ARCHIVE" "payload/zykh_voice/models/tts/$entry" >"$MODEL_DIR/$entry" \
    || fail "部署包中缺少模型文件：$entry"
  [ -s "$MODEL_DIR/$entry" ] || fail "模型文件为空：$MODEL_DIR/$entry"
done

export HOST_OFFLINE_TTS_MODEL_ROOT="$MODEL_ROOT"
cd "$ROOT_DIR/backend"
"$PYTHON_BIN" - <<'PY'
from app.services.host_offline_tts import HostOfflineTts

result = HostOfflineTts().status()
if not result.get("ready"):
    raise SystemExit(f"主机离线 TTS 资源检查失败：{result}")
print("主机离线 TTS 资源检查通过。")
PY

log "主机离线 TTS 已就绪：$MODEL_ROOT"
log "启动后端后可执行：curl -X POST http://127.0.0.1:8000/api/audio/host/warmup"
