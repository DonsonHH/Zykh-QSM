#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
GATEWAY_DIR="$REPO_ROOT/zykh_station_app/qsm_gateway"
BUNDLE="${ASR_BUNDLE_ZIP:-}"
VOICE_ROOT="${ZYKH_VOICE_ROOT:-/userdata/zykh_voice}"
APP_ROOT="${ZYKH_APP_ROOT:-/userdata/zykh_app}"
HOST_PORT="${QSM_LOCAL_ASR_FORWARD_HOST_PORT:-18084}"
DEVICE_PORT="${QSM_LOCAL_ASR_FORWARD_DEVICE_PORT:-6006}"
TEMP_DIR=""

log() {
  printf '[offline-asr] %s\n' "$*"
}

fail() {
  printf '[offline-asr] FAIL: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  [ -z "$TEMP_DIR" ] || rm -rf "$TEMP_DIR"
}
trap cleanup EXIT INT TERM

for command in adb unzip sha256sum awk grep nc; do
  command -v "$command" >/dev/null 2>&1 || fail "主机缺少命令：$command"
done

if [ -z "$BUNDLE" ]; then
  for candidate in "$REPO_ROOT"/QSM368ZP-offline-asr-migration*.zip; do
    if [ -f "$candidate" ]; then
      BUNDLE="$candidate"
      break
    fi
  done
fi
[ -f "$BUNDLE" ] || fail "找不到离线 ASR 部署包；请设置 ASR_BUNDLE_ZIP。"

for file in \
  "$GATEWAY_DIR/asr_ws_client.pl" \
  "$GATEWAY_DIR/start_asr_service.sh" \
  "$GATEWAY_DIR/offline_asr_resident.sh" \
  "$GATEWAY_DIR/offline_asr_paraformer.sh" \
  "$GATEWAY_DIR/start_station_gateway.sh" \
  "$GATEWAY_DIR/patch_station_gateway.pl"; do
  [ -s "$file" ] || fail "仓库缺少接入文件：$file"
done

if [ -n "${ADB_SERIAL:-}" ]; then
  ADB_PREFIX="adb -s $ADB_SERIAL"
else
  DEVICES="$(adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" { print $1 }')"
  [ -n "$DEVICES" ] || fail "未检测到 QSM 设备。"
  DEVICE_COUNT="$(printf '%s\n' "$DEVICES" | wc -l | tr -d ' ')"
  [ "$DEVICE_COUNT" -eq 1 ] || fail "检测到 $DEVICE_COUNT 个 QSM 设备，请设置 ADB_SERIAL。"
  SERIAL="$(printf '%s\n' "$DEVICES" | head -n 1)"
  ADB_PREFIX="adb -s $SERIAL"
fi

ARCH="$($ADB_PREFIX shell uname -m 2>/dev/null | tr -d '\r')"
[ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ] || fail "部署包仅支持 ARM64，当前为 $ARCH。"
$ADB_PREFIX shell "test -s '$APP_ROOT/server.pl'" >/dev/null 2>&1 \
  || fail "板端缺少既有 $APP_ROOT/server.pl；请先部署主网关，ASR 部署不会从历史源码覆写它。"

TEMP_DIR="$(mktemp -d /tmp/zykh-offline-asr.XXXXXX)"
unzip -q "$BUNDLE" 'payload/*' 'test-audio/penicillin-allergy.wav' -d "$TEMP_DIR"

check_checksum() {
  expected="$1"
  path="$2"
  [ -s "$path" ] || fail "部署包缺少：$path"
  actual="$(sha256sum "$path" | awk '{print $1}')"
  [ "$actual" = "$expected" ] || fail "文件校验失败：$path"
}

check_checksum 3ef6c19369b912f7caf3cef8e545c5ccd1a33d9d7ec792a46668dc41c4b229ec "$TEMP_DIR/payload/models/asr-paraformer/model.int8.onnx"
check_checksum 4b2d964e18b9cf139b473003b6698fb2ed9a2a5ec55b93daa677b28f578897aa "$TEMP_DIR/payload/models/asr-paraformer/tokens.txt"
check_checksum 57cb6cc8e13999c33bf115e78db343be42467c8641276b549a4321af88db842d "$TEMP_DIR/payload/runtime/bin/sherpa-onnx-offline"
check_checksum 511f9bb29be471f5485896eb68ab47455dd46a46793d0278f79ae2c39fcc3c2e "$TEMP_DIR/payload/runtime/bin/sherpa-onnx-offline-websocket-server"
check_checksum 17e6abdb3cac548fed3d351e08465d491b4baf84622d070dc449c26ea571a0ea "$TEMP_DIR/payload/runtime/lib/libonnxruntime.so"
check_checksum 8c89846357845287d7dc560664d262dd55d9c4b9f39a5d29072e17bf10dbbf7a "$TEMP_DIR/payload/runtime/lib/libsherpa-onnx-c-api.so"
check_checksum ed32a67a79c23a2495d63cb32c389cbb16340bf530abb0877b023fb2480084cc "$TEMP_DIR/payload/runtime/lib/libsherpa-onnx-cxx-api.so"

log "停止并删除旧 Zipformer 离线识别模块。"
$ADB_PREFIX shell "if [ -s '$APP_ROOT/data/local-asr.pid' ]; then kill \$(cat '$APP_ROOT/data/local-asr.pid') 2>/dev/null || true; fi; rm -rf '$APP_ROOT/local_asr'; rm -f '$APP_ROOT/scripts/start_local_asr.sh' '$APP_ROOT/data/local-asr.pid' '$APP_ROOT/data/local-asr.log'" >/dev/null

log "部署 Paraformer 模型、运行库和常驻服务。"
$ADB_PREFIX shell "mkdir -p '$VOICE_ROOT/runtime/bin' '$VOICE_ROOT/runtime/lib' '$VOICE_ROOT/models/asr-paraformer' '$APP_ROOT/scripts' '$APP_ROOT/data/asr-service'" >/dev/null
$ADB_PREFIX push "$TEMP_DIR/payload/runtime/bin/sherpa-onnx-offline" "$VOICE_ROOT/runtime/bin/" >/dev/null
$ADB_PREFIX push "$TEMP_DIR/payload/runtime/bin/sherpa-onnx-offline-websocket-server" "$VOICE_ROOT/runtime/bin/" >/dev/null
$ADB_PREFIX push "$TEMP_DIR/payload/runtime/lib/libonnxruntime.so" "$VOICE_ROOT/runtime/lib/" >/dev/null
$ADB_PREFIX push "$TEMP_DIR/payload/runtime/lib/libsherpa-onnx-c-api.so" "$VOICE_ROOT/runtime/lib/" >/dev/null
$ADB_PREFIX push "$TEMP_DIR/payload/runtime/lib/libsherpa-onnx-cxx-api.so" "$VOICE_ROOT/runtime/lib/" >/dev/null
$ADB_PREFIX push "$TEMP_DIR/payload/models/asr-paraformer/model.int8.onnx" "$VOICE_ROOT/models/asr-paraformer/" >/dev/null
$ADB_PREFIX push "$TEMP_DIR/payload/models/asr-paraformer/tokens.txt" "$VOICE_ROOT/models/asr-paraformer/" >/dev/null
$ADB_PREFIX push "$GATEWAY_DIR/asr_ws_client.pl" "$APP_ROOT/scripts/" >/dev/null
$ADB_PREFIX push "$GATEWAY_DIR/start_asr_service.sh" "$APP_ROOT/scripts/" >/dev/null
$ADB_PREFIX push "$GATEWAY_DIR/offline_asr_resident.sh" "$APP_ROOT/scripts/" >/dev/null
$ADB_PREFIX push "$GATEWAY_DIR/offline_asr_paraformer.sh" "$APP_ROOT/scripts/" >/dev/null
$ADB_PREFIX shell "cp '$APP_ROOT/scripts/offline_asr_resident.sh' '$APP_ROOT/scripts/offline_asr.sh'; chmod 755 '$VOICE_ROOT/runtime/bin/sherpa-onnx-offline' '$VOICE_ROOT/runtime/bin/sherpa-onnx-offline-websocket-server' '$APP_ROOT/scripts/asr_ws_client.pl' '$APP_ROOT/scripts/start_asr_service.sh' '$APP_ROOT/scripts/offline_asr_resident.sh' '$APP_ROOT/scripts/offline_asr_paraformer.sh' '$APP_ROOT/scripts/offline_asr.sh'" >/dev/null

log "同步板端兼容 API 并预热模型。"
$ADB_PREFIX push "$GATEWAY_DIR/patch_station_gateway.pl" "$APP_ROOT/scripts/patch_station_gateway.pl" >/dev/null
$ADB_PREFIX push "$GATEWAY_DIR/start_station_gateway.sh" "$APP_ROOT/scripts/start_station_gateway.sh" >/dev/null
$ADB_PREFIX shell "chmod 755 '$APP_ROOT/scripts/patch_station_gateway.pl' '$APP_ROOT/scripts/start_station_gateway.sh' && perl '$APP_ROOT/scripts/patch_station_gateway.pl' '$APP_ROOT/server.pl' && '$APP_ROOT/scripts/start_asr_service.sh' start && QSM_HOME='$APP_ROOT' PORT=8080 sh '$APP_ROOT/scripts/start_station_gateway.sh'" \
  >/dev/null || fail "Paraformer 或补丁后的外设网关启动失败。"

$ADB_PREFIX forward "tcp:$HOST_PORT" "tcp:$DEVICE_PORT" >/dev/null || fail "ASR 端口转发失败。"
nc -z -w 3 127.0.0.1 "$HOST_PORT" >/dev/null 2>&1 \
  || fail "ASR 端口转发已建立，但常驻识别服务不可访问。"

log "使用部署包测试音频验证真实板端识别。"
$ADB_PREFIX push "$TEMP_DIR/test-audio/penicillin-allergy.wav" /tmp/zykh-asr-test.wav >/dev/null
RESULT="$($ADB_PREFIX shell "'$APP_ROOT/scripts/offline_asr.sh' /tmp/zykh-asr-test.wav" 2>&1 | tr -d '\r')"
printf '%s\n' "$RESULT"
printf '%s\n' "$RESULT" | grep -Eq '"text"[[:space:]]*:[[:space:]]*"[^"]+"' \
  || fail "板端识别未返回有效文字。"

log "新离线 ASR 已部署：Paraformer resident，主机 ws://127.0.0.1:$HOST_PORT。"
