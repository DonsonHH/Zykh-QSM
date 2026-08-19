#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
ARCHIVE="${1:-$REPO_ROOT/智药康护-QSM368ZP离线TTS部署包(1).zip}"
ADB_BIN="${ADB_BIN:-adb}"
VOICE_ROOT="${QSM_VOICE_ROOT:-/userdata/zykh_voice}"
APP_ROOT="${QSM_HOME:-/userdata/zykh_app}"
STATION_PATCH="$REPO_ROOT/zykh_station_app/qsm_gateway/patch_station_gateway.pl"
STATION_START="$REPO_ROOT/zykh_station_app/qsm_gateway/start_station_gateway.sh"
STATION_CABINET_LIGHT_PROTOCOL="$REPO_ROOT/zykh_station_app/qsm_gateway/lib/Zykh/CabinetLightProtocol.pm"
TTS_SCRIPT="$REPO_ROOT/zykh_station_app/qsm_gateway/offline_tts.sh"

log() {
  printf '[qsm-offline-tts] %s\n' "$*"
}

fail() {
  printf '[qsm-offline-tts] FAIL: %s\n' "$*" >&2
  exit 1
}

for command in "$ADB_BIN" unzip sha256sum awk; do
  command -v "$command" >/dev/null 2>&1 || fail "缺少命令：$command"
done
[ -f "$ARCHIVE" ] || fail "未找到离线 TTS 部署包：$ARCHIVE"
[ -f "$STATION_PATCH" ] || fail "未找到板端网关补丁：$STATION_PATCH"
[ -f "$STATION_START" ] || fail "未找到板端网关启动脚本：$STATION_START"
[ -f "$STATION_CABINET_LIGHT_PROTOCOL" ] || fail "未找到分类柜灯光协议模块：$STATION_CABINET_LIGHT_PROTOCOL"
[ -f "$TTS_SCRIPT" ] || fail "未找到板端离线合成脚本：$TTS_SCRIPT"

if [ -n "${ADB_SERIAL:-}" ]; then
  ADB_PREFIX="$ADB_BIN -s $ADB_SERIAL"
else
  DEVICES="$($ADB_BIN devices 2>/dev/null | awk 'NR > 1 && $2 == "device" {print $1}')"
  [ -n "$DEVICES" ] || fail "未检测到 QSM 设备"
  DEVICE_COUNT="$(printf '%s\n' "$DEVICES" | wc -l | tr -d ' ')"
  [ "$DEVICE_COUNT" -eq 1 ] || fail "检测到 $DEVICE_COUNT 个 QSM 设备，请设置 ADB_SERIAL"
  ADB_PREFIX="$ADB_BIN -s $DEVICES"
fi

TEMP_DIR="$(mktemp -d /tmp/zykh-qsm-tts.XXXXXX)" || fail "无法创建临时目录"
trap 'rm -rf "$TEMP_DIR"' EXIT HUP INT TERM
unzip -q "$ARCHIVE" 'payload/zykh_voice/*' -d "$TEMP_DIR" \
  || fail "离线 TTS 部署包解压失败"
PAYLOAD="$TEMP_DIR/payload/zykh_voice"

for relative in \
  runtime/bin/sherpa-onnx-offline-tts \
  runtime/lib/libonnxruntime.so \
  runtime/lib/libsherpa-onnx-c-api.so \
  runtime/lib/libsherpa-onnx-cxx-api.so \
  models/tts/zh_CN-xiao_ya-medium.onnx \
  models/tts/lexicon.txt \
  models/tts/tokens.txt \
  models/tts/phone.fst \
  models/tts/date.fst \
  models/tts/number.fst; do
  [ -s "$PAYLOAD/$relative" ] || fail "部署包缺少：$relative"
done

ARCH="$($ADB_PREFIX shell uname -m | tr -d '\r')"
case "$ARCH" in
  aarch64|arm64) ;;
  *) fail "不支持的板端架构：$ARCH" ;;
esac

log "上传板端离线语音模型和运行库"
$ADB_PREFIX shell "mkdir -p '$VOICE_ROOT' '$APP_ROOT/scripts/Zykh' '$APP_ROOT/data/audio'" >/dev/null \
  || fail "创建板端目录失败"
$ADB_PREFIX push "$PAYLOAD/." "$VOICE_ROOT/" >/dev/null || fail "上传语音资源失败"
$ADB_PREFIX push "$TTS_SCRIPT" "$APP_ROOT/scripts/offline_tts.sh" >/dev/null \
  || fail "上传板端合成脚本失败"
$ADB_PREFIX push "$STATION_PATCH" "$APP_ROOT/scripts/patch_station_gateway.pl" >/dev/null \
  || fail "上传板端语音路由补丁失败"
$ADB_PREFIX push "$STATION_START" "$APP_ROOT/scripts/start_station_gateway.sh" >/dev/null \
  || fail "上传板端网关启动脚本失败"
$ADB_PREFIX push "$STATION_CABINET_LIGHT_PROTOCOL" "$APP_ROOT/scripts/Zykh/CabinetLightProtocol.pm" >/dev/null \
  || fail "上传分类柜灯光协议模块失败"
$ADB_PREFIX shell "chmod 755 '$VOICE_ROOT/runtime/bin/sherpa-onnx-offline-tts' '$APP_ROOT/scripts/offline_tts.sh' '$APP_ROOT/scripts/patch_station_gateway.pl' '$APP_ROOT/scripts/start_station_gateway.sh'" >/dev/null \
  || fail "设置板端文件权限失败"

for relative in runtime/bin/sherpa-onnx-offline-tts runtime/lib/libonnxruntime.so models/tts/zh_CN-xiao_ya-medium.onnx models/tts/lexicon.txt; do
  LOCAL_HASH="$(sha256sum "$PAYLOAD/$relative" | awk '{print $1}')"
  REMOTE_HASH="$($ADB_PREFIX shell "sha256sum '$VOICE_ROOT/$relative' | awk '{print \\$1}'" | tr -d '\r')"
  [ "$LOCAL_HASH" = "$REMOTE_HASH" ] || fail "校验失败：$relative"
done

log "执行不联网的板端合成自检"
$ADB_PREFIX shell "'$APP_ROOT/scripts/offline_tts.sh' '智药康护离线语音准备完成。' '$APP_ROOT/data/audio/offline-tts-deploy-test.wav'" >/dev/null \
  || fail "板端离线语音合成自检失败"
$ADB_PREFIX shell "test -s '$APP_ROOT/data/audio/offline-tts-deploy-test.wav'" >/dev/null \
  || fail "板端离线语音未生成有效音频"
$ADB_PREFIX shell "perl '$APP_ROOT/scripts/patch_station_gateway.pl' '$APP_ROOT/server.pl' && QSM_HOME='$APP_ROOT' sh '$APP_ROOT/scripts/start_station_gateway.sh'" >/dev/null \
  || fail "启用并重启板端离线语音路由失败"
log "板端离线语音部署完成"
