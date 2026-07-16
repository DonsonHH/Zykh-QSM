#!/usr/bin/env sh
set -u

HOST_PORT="${QSM_FORWARD_HOST_PORT:-18080}"
DEVICE_PORT="${QSM_FORWARD_DEVICE_PORT:-8080}"
FACE_HOST_PORT="${QSM_FACE_FORWARD_HOST_PORT:-18081}"
FACE_DEVICE_PORT="${QSM_FACE_FORWARD_DEVICE_PORT:-8081}"
AUDIO_HOST_PORT="${QSM_AUDIO_CAPTURE_FORWARD_HOST_PORT:-18082}"
AUDIO_DEVICE_PORT="${QSM_AUDIO_CAPTURE_FORWARD_DEVICE_PORT:-8082}"
FINGERPRINT_HOST_PORT="${QSM_FINGERPRINT_FORWARD_HOST_PORT:-18086}"
FINGERPRINT_DEVICE_PORT="${QSM_FINGERPRINT_FORWARD_DEVICE_PORT:-8086}"
QSM_HOME="${QSM_HOME:-/userdata/zykh_app}"
QSM_FACE_HOME="${QSM_FACE_HOME:-/userdata/qsm-face}"
QSM_AUDIO_HOME="${QSM_AUDIO_HOME:-/userdata/qsm-audio}"
QSM_FINGERPRINT_HOME="${QSM_FINGERPRINT_HOME:-/userdata/qsm-fingerprint}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
LOCAL_START="$REPO_ROOT/zykh_station_app/qsm_gateway/start_station_gateway.sh"
LOCAL_VITALS_UART="$REPO_ROOT/zykh_station_app/qsm_gateway/read_vitals_uart8.pl"
LOCAL_FACE_GATEWAY="$REPO_ROOT/zykh_station_app/qsm_gateway/face_gateway.pl"
LOCAL_FACE_START="$REPO_ROOT/zykh_station_app/qsm_gateway/start_face_gateway.sh"
LOCAL_AUDIO_GATEWAY="$REPO_ROOT/zykh_station_app/qsm_gateway/audio_capture_gateway.pl"
LOCAL_AUDIO_START="$REPO_ROOT/zykh_station_app/qsm_gateway/start_audio_capture_gateway.sh"
LOCAL_FINGERPRINT_GATEWAY="$REPO_ROOT/zykh_station_app/qsm_gateway/fingerprint_gateway.pl"
LOCAL_FINGERPRINT_START="$REPO_ROOT/zykh_station_app/qsm_gateway/start_fingerprint_gateway.sh"
LOCAL_FINGERPRINT_DRIVER="$REPO_ROOT/zykh_station_app/qsm_gateway/as608.pl"
FACE_BUNDLE="${QSM_FACE_BUNDLE:-}"
FINGERPRINT_BUNDLE="${QSM_FINGERPRINT_BUNDLE:-}"
TEMP_DIR=""

log() {
  printf '[qsm-deploy] %s\n' "$*"
}

fail() {
  printf '[qsm-deploy] FAIL: %s\n' "$*" >&2
  exit 1
}

[ -f "$LOCAL_START" ] || fail "找不到外设网关启动脚本：$LOCAL_START"
[ -f "$LOCAL_VITALS_UART" ] || fail "找不到 UART8 体征读取器：$LOCAL_VITALS_UART"
[ -f "$LOCAL_FACE_GATEWAY" ] || fail "找不到人脸识别网关：$LOCAL_FACE_GATEWAY"
[ -f "$LOCAL_FACE_START" ] || fail "找不到人脸识别启动脚本：$LOCAL_FACE_START"
[ -f "$LOCAL_AUDIO_GATEWAY" ] || fail "找不到麦克风采集网关：$LOCAL_AUDIO_GATEWAY"
[ -f "$LOCAL_AUDIO_START" ] || fail "找不到麦克风采集启动脚本：$LOCAL_AUDIO_START"
[ -f "$LOCAL_FINGERPRINT_GATEWAY" ] || fail "找不到指纹识别网关：$LOCAL_FINGERPRINT_GATEWAY"
[ -f "$LOCAL_FINGERPRINT_START" ] || fail "找不到指纹识别启动脚本：$LOCAL_FINGERPRINT_START"
[ -f "$LOCAL_FINGERPRINT_DRIVER" ] || fail "找不到指纹驱动：$LOCAL_FINGERPRINT_DRIVER"
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

log "部署 QSM 人脸识别 HTTP 适配"
$ADB_PREFIX shell "mkdir -p '$QSM_FACE_HOME/data' '$QSM_FACE_HOME/logs' '$QSM_FACE_HOME/lib'" >/dev/null || fail "创建板端人脸目录失败"
$ADB_PREFIX push "$LOCAL_FACE_GATEWAY" "$QSM_FACE_HOME/face_gateway.pl" >/dev/null || fail "推送人脸识别网关失败"
$ADB_PREFIX push "$LOCAL_FACE_START" "$QSM_FACE_HOME/start_face_gateway.sh" >/dev/null || fail "推送人脸识别启动脚本失败"

if ! $ADB_PREFIX shell "test -x '$QSM_FACE_HOME/qsm_face' -a -s '$QSM_FACE_HOME/Gundam_RK356X' -a -s '$QSM_FACE_HOME/lib/libInspireFace.so'" >/dev/null 2>&1; then
  if [ -z "$FACE_BUNDLE" ] && [ -f "/home/jetson/QSM368ZP-board-face-recognition(1).zip" ]; then
    FACE_BUNDLE="/home/jetson/QSM368ZP-board-face-recognition(1).zip"
  fi
  [ -n "$FACE_BUNDLE" ] && [ -f "$FACE_BUNDLE" ] || fail "板端缺少人脸运行包；请设置 QSM_FACE_BUNDLE 指向用户提供的 zip。"
  command -v unzip >/dev/null 2>&1 || fail "未找到 unzip，无法解包人脸运行包。"
  TEMP_DIR="$(mktemp -d)" || fail "无法创建临时目录。"
  unzip -q "$FACE_BUNDLE" -d "$TEMP_DIR" || fail "解包人脸运行包失败。"
  [ -x "$TEMP_DIR/board/qsm_face" ] || fail "人脸运行包结构不正确，缺少 board/qsm_face。"
  $ADB_PREFIX push "$TEMP_DIR/board/qsm_face" "$TEMP_DIR/board/Gundam_RK356X" "$TEMP_DIR/board/face.sh" "$TEMP_DIR/board/stop.sh" "$QSM_FACE_HOME/" >/dev/null \
    || fail "推送人脸程序或模型失败"
  $ADB_PREFIX push "$TEMP_DIR/board/lib/libInspireFace.so" "$TEMP_DIR/board/lib/librknnrt.so" "$QSM_FACE_HOME/lib/" >/dev/null \
    || fail "推送人脸运行库失败"
  rm -rf "$TEMP_DIR"
  TEMP_DIR=""
fi

$ADB_PREFIX shell "chmod +x '$QSM_FACE_HOME/qsm_face' '$QSM_FACE_HOME/face.sh' '$QSM_FACE_HOME/stop.sh' '$QSM_FACE_HOME/start_face_gateway.sh'; QSM_FACE_HOME='$QSM_FACE_HOME' QSM_FACE_GATEWAY_PORT='$FACE_DEVICE_PORT' sh '$QSM_FACE_HOME/start_face_gateway.sh'" >/dev/null \
  || fail "启动板端人脸识别网关失败"

log "部署 QSM FF Camera 麦克风采集适配"
$ADB_PREFIX shell "mkdir -p '$QSM_AUDIO_HOME/logs'" >/dev/null || fail "创建板端麦克风目录失败"
$ADB_PREFIX push "$LOCAL_AUDIO_GATEWAY" "$QSM_AUDIO_HOME/audio_capture_gateway.pl" >/dev/null || fail "推送麦克风采集网关失败"
$ADB_PREFIX push "$LOCAL_AUDIO_START" "$QSM_AUDIO_HOME/start_audio_capture_gateway.sh" >/dev/null || fail "推送麦克风启动脚本失败"
$ADB_PREFIX shell "chmod +x '$QSM_AUDIO_HOME/audio_capture_gateway.pl' '$QSM_AUDIO_HOME/start_audio_capture_gateway.sh'; QSM_AUDIO_HOME='$QSM_AUDIO_HOME' QSM_AUDIO_CAPTURE_PORT='$AUDIO_DEVICE_PORT' sh '$QSM_AUDIO_HOME/start_audio_capture_gateway.sh'" >/dev/null \
  || fail "启动板端麦克风采集网关失败"

log "部署 QSM AS608 指纹识别适配"
$ADB_PREFIX shell "mkdir -p '$QSM_FINGERPRINT_HOME/logs'" >/dev/null || fail "创建板端指纹目录失败"
if ! $ADB_PREFIX shell "test -f '$QSM_HOME/scripts/as608.pl' -a -x '$QSM_HOME/scripts/init_fingerprint.sh' -a -x '$QSM_HOME/bin/ch340_init'" >/dev/null 2>&1; then
  if [ -z "$FINGERPRINT_BUNDLE" ] && [ -f "$REPO_ROOT/QSM368ZP-AS608-offline-deploy(1).zip" ]; then
    FINGERPRINT_BUNDLE="$REPO_ROOT/QSM368ZP-AS608-offline-deploy(1).zip"
  fi
  [ -n "$FINGERPRINT_BUNDLE" ] && [ -f "$FINGERPRINT_BUNDLE" ] \
    || fail "板端缺少 AS608 驱动；请设置 QSM_FINGERPRINT_BUNDLE 指向离线部署包。"
  command -v unzip >/dev/null 2>&1 || fail "未找到 unzip，无法解包 AS608 离线部署包。"
  TEMP_DIR="$(mktemp -d)" || fail "无法创建 AS608 临时部署目录。"
  unzip -q "$FINGERPRINT_BUNDLE" -d "$TEMP_DIR" || fail "解包 AS608 离线部署包失败。"
  FINGERPRINT_PAYLOAD="$(find "$TEMP_DIR" -type f -path '*/payload/as608.pl' -print | head -n 1)"
  [ -n "$FINGERPRINT_PAYLOAD" ] || fail "AS608 离线部署包结构不正确，缺少 payload/as608.pl。"
  FINGERPRINT_PAYLOAD_DIR="$(dirname "$FINGERPRINT_PAYLOAD")"
  [ -f "$FINGERPRINT_PAYLOAD_DIR/init_fingerprint.sh" ] -a -f "$FINGERPRINT_PAYLOAD_DIR/ch340_init" \
    || fail "AS608 离线部署包缺少初始化脚本或 CH340 程序。"
  $ADB_PREFIX shell "mkdir -p '$QSM_HOME/bin' '$QSM_HOME/scripts'" >/dev/null || fail "创建 AS608 板端目录失败"
  $ADB_PREFIX push "$FINGERPRINT_PAYLOAD_DIR/as608.pl" "$FINGERPRINT_PAYLOAD_DIR/init_fingerprint.sh" "$QSM_HOME/scripts/" >/dev/null \
    || fail "推送 AS608 Perl 驱动失败"
  $ADB_PREFIX push "$FINGERPRINT_PAYLOAD_DIR/ch340_init" "$QSM_HOME/bin/ch340_init" >/dev/null \
    || fail "推送 CH340 初始化程序失败"
  $ADB_PREFIX shell "chmod 755 '$QSM_HOME/bin/ch340_init' '$QSM_HOME/scripts/as608.pl' '$QSM_HOME/scripts/init_fingerprint.sh'; sh '$QSM_HOME/scripts/init_fingerprint.sh' restart" >/dev/null \
    || fail "AS608 USB 初始化失败，请检查 3.3V 供电和 TX/RX 接线。"
  rm -rf "$TEMP_DIR"
  TEMP_DIR=""
fi
$ADB_PREFIX push "$LOCAL_FINGERPRINT_DRIVER" "$QSM_HOME/scripts/as608.pl" >/dev/null || fail "推送优化后的 AS608 指纹驱动失败"
$ADB_PREFIX push "$LOCAL_FINGERPRINT_GATEWAY" "$QSM_FINGERPRINT_HOME/fingerprint_gateway.pl" >/dev/null || fail "推送指纹识别网关失败"
$ADB_PREFIX push "$LOCAL_FINGERPRINT_START" "$QSM_FINGERPRINT_HOME/start_fingerprint_gateway.sh" >/dev/null || fail "推送指纹启动脚本失败"
$ADB_PREFIX shell "chmod +x '$QSM_HOME/scripts/as608.pl' '$QSM_FINGERPRINT_HOME/fingerprint_gateway.pl' '$QSM_FINGERPRINT_HOME/start_fingerprint_gateway.sh'; QSM_FINGERPRINT_HOME='$QSM_FINGERPRINT_HOME' QSM_FINGERPRINT_PORT='$FINGERPRINT_DEVICE_PORT' sh '$QSM_FINGERPRINT_HOME/start_fingerprint_gateway.sh'" >/dev/null \
  || fail "启动板端指纹识别网关失败"

log "建立端口转发：127.0.0.1:$HOST_PORT -> tcp:$DEVICE_PORT"
$ADB_PREFIX forward "tcp:${HOST_PORT}" "tcp:${DEVICE_PORT}" >/dev/null 2>&1 || fail "端口转发失败"
log "建立人脸接口转发：127.0.0.1:$FACE_HOST_PORT -> tcp:$FACE_DEVICE_PORT"
$ADB_PREFIX forward "tcp:${FACE_HOST_PORT}" "tcp:${FACE_DEVICE_PORT}" >/dev/null 2>&1 || fail "人脸接口端口转发失败"
log "建立麦克风接口转发：127.0.0.1:$AUDIO_HOST_PORT -> tcp:$AUDIO_DEVICE_PORT"
$ADB_PREFIX forward "tcp:${AUDIO_HOST_PORT}" "tcp:${AUDIO_DEVICE_PORT}" >/dev/null 2>&1 || fail "麦克风接口端口转发失败"
log "建立指纹接口转发：127.0.0.1:$FINGERPRINT_HOST_PORT -> tcp:$FINGERPRINT_DEVICE_PORT"
$ADB_PREFIX forward "tcp:${FINGERPRINT_HOST_PORT}" "tcp:${FINGERPRINT_DEVICE_PORT}" >/dev/null 2>&1 || fail "指纹接口端口转发失败"

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

FACE_STATUS="$(curl -fsS --max-time 12 "http://127.0.0.1:${FACE_HOST_PORT}/api/face/status" 2>/dev/null)" \
  || fail "人脸识别网关已部署，但状态接口不可访问。"
case "$FACE_STATUS" in
  *'"runtime_available":true'*) log "人脸识别运行库、模型和摄像头已就绪。" ;;
  *) fail "人脸识别状态未就绪：$FACE_STATUS" ;;
esac

AUDIO_STATUS="$(curl -fsS --max-time 5 "http://127.0.0.1:${AUDIO_HOST_PORT}/api/audio/capture/status" 2>/dev/null)" \
  || fail "麦克风采集网关已部署，但状态接口不可访问。"
case "$AUDIO_STATUS" in
  *'"source":"FF Camera"'*'"ok":true'*) log "FF Camera 麦克风采集已就绪。" ;;
  *'"ok":true'*'"source":"FF Camera"'*) log "FF Camera 麦克风采集已就绪。" ;;
  *) fail "麦克风采集状态未就绪：$AUDIO_STATUS" ;;
esac

FINGERPRINT_STATUS="$(curl -fsS --max-time 10 "http://127.0.0.1:${FINGERPRINT_HOST_PORT}/api/fingerprint/status" 2>/dev/null)" \
  || fail "指纹识别网关已部署，但状态接口不可访问。"
case "$FINGERPRINT_STATUS" in
  *'"ok":true'*) log "AS608 指纹识别模块已就绪。" ;;
  *) fail "指纹识别状态未就绪：$FINGERPRINT_STATUS" ;;
esac

log "读取一次 UART8 综合体征，未放手指时出现 awaiting_finger 也表示硬件链路已响应。"
VITALS_RESPONSE="$(curl -fsS --max-time 32 -X POST "http://127.0.0.1:${HOST_PORT}/api/vitals/read_all" 2>/dev/null)" \
  || fail "外设网关可访问，但综合体征接口读取失败。"
case "$VITALS_RESPONSE" in
  *UART8-vitals-24B*)
    log "部署完成：外设网关与 UART8 体征模块均已响应。"
    ;;
  *)
    fail "综合体征接口未返回 UART8-vitals-24B 标识，请检查板端启动环境。"
    ;;
esac
