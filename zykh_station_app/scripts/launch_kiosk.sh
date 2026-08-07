#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
APP_URL="${APP_URL:-http://127.0.0.1:5173}"
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
KIOSK_WIDTH="${KIOSK_WIDTH:-}"
KIOSK_HEIGHT="${KIOSK_HEIGHT:-}"
KIOSK_OUTPUT="${KIOSK_OUTPUT:-}"
KIOSK_SCALE="${KIOSK_SCALE:-2}"
KIOSK_CHANGE_RESOLUTION="${KIOSK_CHANGE_RESOLUTION:-0}"
KIOSK_SAFE_GRAPHICS="${KIOSK_SAFE_GRAPHICS:-1}"
KIOSK_RESTORE_RESOLUTION="${KIOSK_RESTORE_RESOLUTION:-1}"
KIOSK_BROWSER_LOG="${KIOSK_BROWSER_LOG:-file}"
KIOSK_AUDIO_RELAY="${KIOSK_AUDIO_RELAY:-1}"
KIOSK_OFFLINE_AI="${KIOSK_OFFLINE_AI:-0}"
KIOSK_RESTART_BACKEND="${KIOSK_RESTART_BACKEND:-1}"
KIOSK_TOUCH_KEYBOARD="${KIOSK_TOUCH_KEYBOARD:-1}"
RUN_DIR="$ROOT_DIR/data/run"
BROWSER_PID=""
AUDIO_RELAY_PID=""
AUDIO_RELAY_PROCESS_GROUP="0"
AUDIO_RELAY_STARTED="0"
CLEANUP_STARTED="0"
KIOSK_GUARD_STARTED="0"
KIOSK_GUARD_DONE="$RUN_DIR/kiosk-cleanup.$$.done"
KIOSK_GUARD_LOG="$RUN_DIR/kiosk-cleanup.log"
RESTORE_OUTPUT=""
RESTORE_MODE=""

mkdir -p "$RUN_DIR"

log() {
  printf '[kiosk] %s\n' "$*"
}

warn() {
  printf '[kiosk] WARN: %s\n' "$*" >&2
}

start_browser() {
  if [ "$KIOSK_BROWSER_LOG" = "terminal" ]; then
    "$@" &
  else
    log "浏览器日志：$RUN_DIR/chromium.log"
    "$@" >"$RUN_DIR/chromium.log" 2>&1 &
  fi
  BROWSER_PID="$!"
}

current_mode_for_output() {
  xrandr --query | awk -v output="$1" '
    $1 == output && $2 == "connected" { found = 1; next }
    found && /^[[:space:]]/ && /\*/ { print $1; exit }
    found && /^[^[:space:]]/ { found = 0 }
  '
}

restore_resolution() {
  if [ "$KIOSK_RESTORE_RESOLUTION" != "1" ]; then
    return 0
  fi
  if [ -z "$RESTORE_OUTPUT" ] || [ -z "$RESTORE_MODE" ]; then
    return 0
  fi
  if ! command -v xrandr >/dev/null 2>&1; then
    return 0
  fi
  if xrandr --output "$RESTORE_OUTPUT" --mode "$RESTORE_MODE" >/dev/null 2>&1; then
    log "显示输出 $RESTORE_OUTPUT 已恢复到 $RESTORE_MODE。"
  else
    warn "无法恢复显示输出 $RESTORE_OUTPUT 到 $RESTORE_MODE。"
  fi
}

terminate_managed_process() {
  pid="$1"
  process_group="$2"
  if [ -z "$pid" ] || ! kill -0 "$pid" >/dev/null 2>&1; then
    return 0
  fi

  if [ "$process_group" = "1" ]; then
    kill -TERM "-$pid" >/dev/null 2>&1 || kill -TERM "$pid" >/dev/null 2>&1 || true
  else
    kill -TERM "$pid" >/dev/null 2>&1 || true
  fi

  count=0
  while kill -0 "$pid" >/dev/null 2>&1 && [ "$count" -lt 20 ]; do
    count=$((count + 1))
    sleep 0.1
  done

  if kill -0 "$pid" >/dev/null 2>&1; then
    if [ "$process_group" = "1" ]; then
      kill -KILL "-$pid" >/dev/null 2>&1 || kill -KILL "$pid" >/dev/null 2>&1 || true
    else
      kill -KILL "$pid" >/dev/null 2>&1 || true
    fi
  fi
  wait "$pid" 2>/dev/null || true
}

stop_browser() {
  terminate_managed_process "$BROWSER_PID" "0"
}

start_touch_keyboard_if_needed() {
  if [ "$KIOSK_TOUCH_KEYBOARD" != "1" ]; then
    log "应用内屏幕键盘已关闭。"
    return 0
  fi
  log "新版应用内屏幕键盘已就绪，点按可编辑区域会自动弹出。"
}

prepare_chinese_input_method() {
  if [ "$KIOSK_TOUCH_KEYBOARD" != "1" ]; then
    return 0
  fi
  export GTK_IM_MODULE=fcitx
  export QT_IM_MODULE=fcitx
  export XMODIFIERS=@im=fcitx
  if ! command -v fcitx5 >/dev/null 2>&1; then
    warn "未找到 Fcitx5，实体键盘无法使用系统拼音；应用内屏幕键盘仍可离线输入中文。"
    return 0
  fi
  if ! pgrep -x fcitx5 >/dev/null 2>&1; then
    fcitx5 -d >/dev/null 2>&1 || true
    sleep 1
  fi
  if command -v fcitx5-remote >/dev/null 2>&1; then
    fcitx5-remote -s pinyin >/dev/null 2>&1 || warn "未能自动切换拼音输入法，可在系统输入法中手动选择拼音。"
  fi
}

start_audio_relay_if_needed() {
  if [ "$KIOSK_AUDIO_RELAY" != "1" ]; then
    return 0
  fi
  if [ ! -x "$ROOT_DIR/scripts/relay_host_audio_to_qsm.sh" ]; then
    warn "未找到音频转发脚本，跳过外设外放转发。"
    return 0
  fi
  log "启动本机音频转发到外设喇叭..."
  if command -v setsid >/dev/null 2>&1; then
    BACKEND_URL="$BACKEND_URL" setsid sh "$ROOT_DIR/scripts/relay_host_audio_to_qsm.sh" >"$RUN_DIR/audio-relay.log" 2>&1 &
    AUDIO_RELAY_PROCESS_GROUP="1"
  else
    BACKEND_URL="$BACKEND_URL" sh "$ROOT_DIR/scripts/relay_host_audio_to_qsm.sh" >"$RUN_DIR/audio-relay.log" 2>&1 &
    AUDIO_RELAY_PROCESS_GROUP="0"
  fi
  AUDIO_RELAY_PID="$!"
  AUDIO_RELAY_STARTED="1"
  echo "$AUDIO_RELAY_PID" >"$RUN_DIR/audio-relay.pid"
  sleep 1
  if ! kill -0 "$AUDIO_RELAY_PID" >/dev/null 2>&1; then
    warn "本机音频实时转发未启动成功，日志：$RUN_DIR/audio-relay.log"
    AUDIO_RELAY_PID=""
    AUDIO_RELAY_PROCESS_GROUP="0"
    AUDIO_RELAY_STARTED="0"
    rm -f "$RUN_DIR/audio-relay.pid"
  fi
}

stop_audio_relay() {
  terminate_managed_process "$AUDIO_RELAY_PID" "$AUDIO_RELAY_PROCESS_GROUP"
  if [ "$AUDIO_RELAY_STARTED" = "1" ]; then
    curl -sS --max-time 2 -X POST "$BACKEND_URL/api/audio/stream/stop" >/dev/null 2>&1 || true
    rm -f "$RUN_DIR/audio-relay.pid"
    log "本机音频转发已停止。"
  fi
  AUDIO_RELAY_PID=""
  AUDIO_RELAY_PROCESS_GROUP="0"
  AUDIO_RELAY_STARTED="0"
}

cleanup_once() {
  if [ "$CLEANUP_STARTED" = "1" ]; then
    return 0
  fi
  CLEANUP_STARTED="1"
  trap - EXIT
  trap '' HUP INT QUIT TERM
  stop_browser
  stop_audio_relay
  restore_resolution
  if [ "$KIOSK_GUARD_STARTED" = "1" ]; then
    : >"$KIOSK_GUARD_DONE"
  else
    rm -f "$KIOSK_GUARD_DONE"
  fi
}

start_cleanup_guard() {
  guard="$ROOT_DIR/scripts/kiosk_cleanup_guard.sh"
  if [ ! -f "$guard" ]; then
    warn "未找到退出清理守护脚本；仍使用当前进程的退出清理。"
    return 0
  fi

  parent_start="$(awk '{print $22}' "/proc/$$/stat" 2>/dev/null || true)"
  rm -f "$KIOSK_GUARD_DONE"
  if command -v setsid >/dev/null 2>&1; then
    nohup setsid sh "$guard" \
      "$$" \
      "$parent_start" \
      "$BROWSER_PID" \
      "$AUDIO_RELAY_PID" \
      "$AUDIO_RELAY_PROCESS_GROUP" \
      "$BACKEND_URL" \
      "$RESTORE_OUTPUT" \
      "$RESTORE_MODE" \
      "$KIOSK_RESTORE_RESOLUTION" \
      "$KIOSK_GUARD_DONE" \
      >>"$KIOSK_GUARD_LOG" 2>&1 &
  else
    nohup sh "$guard" \
      "$$" \
      "$parent_start" \
      "$BROWSER_PID" \
      "$AUDIO_RELAY_PID" \
      "$AUDIO_RELAY_PROCESS_GROUP" \
      "$BACKEND_URL" \
      "$RESTORE_OUTPUT" \
      "$RESTORE_MODE" \
      "$KIOSK_RESTORE_RESOLUTION" \
      "$KIOSK_GUARD_DONE" \
      >>"$KIOSK_GUARD_LOG" 2>&1 &
  fi
  KIOSK_GUARD_STARTED="1"
  log "退出清理守护已启动。"
}

on_exit() {
  status="$?"
  cleanup_once
  exit "$status"
}

on_signal() {
  status="$1"
  cleanup_once
  exit "$status"
}

trap on_exit EXIT
trap 'on_signal 129' HUP
trap 'on_signal 130' INT
trap 'on_signal 131' QUIT
trap 'on_signal 143' TERM

backend_ready() {
  curl -fsS --max-time 1 "$BACKEND_URL/api/health" >/dev/null 2>&1
}

backend_schema_current() {
  response="$(curl -fsS --max-time 2 "$BACKEND_URL/api/medicines/slot-08-huoxiang-zhengqi" 2>/dev/null || true)"
  [ -n "$response" ] || return 1
  printf '%s' "$response" | grep -q '"indications"' || return 1
  printf '%s' "$response" | grep -q '"dosage"' || return 1
  printf '%s' "$response" | grep -q '"guidance_source"' || return 1
}

backend_port() {
  port="$(printf '%s' "$BACKEND_URL" | sed -n 's#.*:\([0-9][0-9]*\).*#\1#p')"
  printf '%s\n' "${port:-8000}"
}

stop_backend_if_managed() {
  pidfile="$RUN_DIR/backend.pid"
  if [ ! -f "$pidfile" ]; then
    return 0
  fi
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  case "$pid" in
    ''|*[!0-9]*) return 0 ;;
  esac
  if kill -0 "$pid" >/dev/null 2>&1; then
    log "重启后端服务以加载最新配置..."
    kill "$pid" >/dev/null 2>&1 || true
    count=0
    while kill -0 "$pid" >/dev/null 2>&1 && [ "$count" -lt 20 ]; do
      count=$((count + 1))
      sleep 0.2
    done
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  fi
  rm -f "$pidfile"
}

stop_project_backend_processes() {
  port="$(backend_port)"
  stopped=0
  candidates=""
  if command -v pgrep >/dev/null 2>&1; then
    candidates="$(pgrep -f "uvicorn app.main.*--port $port" 2>/dev/null || true)"
  fi
  if command -v lsof >/dev/null 2>&1; then
    listeners="$(lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    candidates="$(printf '%s\n%s\n' "$candidates" "$listeners")"
  fi

  for pid in $(printf '%s\n' "$candidates" | awk 'NF && !seen[$0]++'); do
    case "$pid" in
      ''|*[!0-9]*) continue ;;
    esac
    cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
    cmdline="$(tr '\000' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    case "$cmdline" in
      *uvicorn*app.main:app*) ;;
      *) continue ;;
    esac
    case "$cwd" in
      "$ROOT_DIR/backend"|"$ROOT_DIR/backend/"*)
        log "停止旧后端进程 PID $pid，以加载最新配置..."
        kill "$pid" >/dev/null 2>&1 || true
        stopped=1
        ;;
      *)
        case "$cmdline" in
          *"$ROOT_DIR/backend"*)
            log "停止旧后端进程 PID $pid，以加载最新配置..."
            kill "$pid" >/dev/null 2>&1 || true
            stopped=1
            ;;
        esac
        ;;
    esac
  done

  if [ "$stopped" = "1" ]; then
    count=0
    while [ "$count" -lt 30 ]; do
      if ! backend_ready; then
        break
      fi
      count=$((count + 1))
      sleep 0.2
    done
  fi
}

frontend_ready() {
  if ! curl -fsS --max-time 1 "$APP_URL" >/dev/null 2>&1; then
    return 1
  fi

  style_probe="$(curl -fsS --max-time 2 "$APP_URL/src/styles/app.css" 2>/dev/null || true)"
  if [ -z "$style_probe" ]; then
    return 1
  fi
  if printf '%s' "$style_probe" | grep -q 'const __vite__css = ""'; then
    return 1
  fi
  return 0
}

frontend_port() {
  port="$(printf '%s' "$APP_URL" | sed -n 's#.*:\([0-9][0-9]*\).*#\1#p')"
  printf '%s\n' "${port:-5173}"
}

stop_project_frontend_processes() {
  port="$(frontend_port)"
  if ! command -v pgrep >/dev/null 2>&1; then
    return 0
  fi

  stopped=0
  for pid in $(pgrep -f "vite.*--port $port" 2>/dev/null || true); do
    case "$pid" in
      ''|*[!0-9]*) continue ;;
    esac
    cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
    case "$cwd" in
      "$ROOT_DIR/frontend"|"$ROOT_DIR/frontend/"*)
        log "停止残留前端进程 PID $pid，以加载最新界面..."
        kill "$pid" >/dev/null 2>&1 || true
        stopped=1
        ;;
    esac
  done

  if [ "$stopped" = "1" ]; then
    count=0
    while [ "$count" -lt 20 ]; do
      if ! curl -fsS --max-time 1 "$APP_URL" >/dev/null 2>&1; then
        break
      fi
      count=$((count + 1))
      sleep 0.2
    done
  fi
  rm -f "$RUN_DIR/frontend.pid"
}

wait_for_backend() {
  count=0
  while [ "$count" -lt 30 ]; do
    if backend_ready && backend_schema_current; then
      return 0
    fi
    count=$((count + 1))
    sleep 1
  done
  return 1
}

wait_for_frontend() {
  count=0
  while [ "$count" -lt 40 ]; do
    if frontend_ready; then
      return 0
    fi
    count=$((count + 1))
    sleep 1
  done
  return 1
}

start_backend_if_needed() {
  if [ "$KIOSK_RESTART_BACKEND" = "1" ]; then
    stop_backend_if_managed
    stop_project_backend_processes
  fi

  if backend_ready && backend_schema_current; then
    log "后端已运行：$BACKEND_URL"
    return 0
  fi

  if backend_ready; then
    warn "端口 $(backend_port) 上的后端接口版本过旧，且启动器未能安全停止该进程。"
    warn "请停止占用该端口的旧 FastAPI 进程后重新运行 scripts/launch_kiosk.sh。"
    return 1
  fi

  log "启动后端服务..."
  nohup sh "$ROOT_DIR/scripts/start_backend.sh" >"$RUN_DIR/backend.log" 2>&1 &
  echo "$!" >"$RUN_DIR/backend.pid"

  if wait_for_backend; then
    log "后端启动完成：$BACKEND_URL"
  else
    warn "后端未在预期时间内就绪，日志：$RUN_DIR/backend.log"
  fi
}

start_frontend_if_needed() {
  if frontend_ready; then
    log "前端已运行：$APP_URL"
    return 0
  fi

  stop_project_frontend_processes
  log "启动前端服务..."
  nohup sh "$ROOT_DIR/scripts/start_frontend.sh" >"$RUN_DIR/frontend.log" 2>&1 &
  echo "$!" >"$RUN_DIR/frontend.pid"

  if wait_for_frontend; then
    log "前端启动完成：$APP_URL"
  else
    warn "前端未在预期时间内就绪，日志：$RUN_DIR/frontend.log"
  fi
}

prepare_kiosk_display() {
  if ! command -v xrandr >/dev/null 2>&1; then
    KIOSK_WIDTH="${KIOSK_WIDTH:-1280}"
    KIOSK_HEIGHT="${KIOSK_HEIGHT:-720}"
    warn "未找到 xrandr，无法读取当前显示尺寸；kiosk 将使用 ${KIOSK_WIDTH}x${KIOSK_HEIGHT} 窗口参数。"
    return 0
  fi

  output="$KIOSK_OUTPUT"
  if [ -z "$output" ]; then
    output="$(xrandr --query | awk '/ connected/{print $1; exit}')"
  fi

  if [ -z "$output" ]; then
    KIOSK_WIDTH="${KIOSK_WIDTH:-1280}"
    KIOSK_HEIGHT="${KIOSK_HEIGHT:-720}"
    warn "未检测到可用显示输出；kiosk 将使用 ${KIOSK_WIDTH}x${KIOSK_HEIGHT} 窗口参数。"
    return 0
  fi

  current_mode="$(current_mode_for_output "$output" || true)"
  case "$current_mode" in
    *x*)
      current_width="${current_mode%%x*}"
      current_height="${current_mode#*x}"
      case "$current_width:$current_height" in
        *[!0-9:]*|:|*:)
          current_width=""
          current_height=""
          ;;
      esac
      ;;
    *)
      current_width=""
      current_height=""
      ;;
  esac

  KIOSK_WIDTH="${KIOSK_WIDTH:-${current_width:-1280}}"
  KIOSK_HEIGHT="${KIOSK_HEIGHT:-${current_height:-720}}"

  if [ "$KIOSK_CHANGE_RESOLUTION" != "1" ] || [ "${KIOSK_SKIP_RESOLUTION:-0}" = "1" ]; then
    if [ -n "$current_mode" ]; then
      log "保持显示输出 $output 的当前分辨率 $current_mode；kiosk 使用 ${KIOSK_SCALE}x 缩放。"
    else
      log "保持当前显示分辨率；kiosk 使用 ${KIOSK_SCALE}x 缩放。"
    fi
    return 0
  fi

  mode="${KIOSK_WIDTH}x${KIOSK_HEIGHT}"
  if [ "$mode" = "$current_mode" ]; then
    log "显示输出 $output 已是 $mode；无需切换分辨率。"
    return 0
  fi

  RESTORE_OUTPUT="$output"
  RESTORE_MODE="$current_mode"
  if xrandr --output "$output" --mode "$mode" >/dev/null 2>&1; then
    log "显示输出 $output 已切换到 $mode。"
    return 0
  fi

  if xrandr --size "$mode" >/dev/null 2>&1; then
    log "屏幕已切换到 $mode。"
    return 0
  fi

  warn "当前显示输出不支持 $mode，继续用现有分辨率打开。可用 KIOSK_OUTPUT 指定输出。"
}

find_browser() {
  if command -v chromium >/dev/null 2>&1; then
    printf '%s\n' chromium
  elif command -v chromium-browser >/dev/null 2>&1; then
    printf '%s\n' chromium-browser
  elif command -v google-chrome >/dev/null 2>&1; then
    printf '%s\n' google-chrome
  else
    return 1
  fi
}

install_qsm_tether_helper_if_needed() {
  helper="/usr/local/sbin/zykh-qsm-tether"
  installer="$ROOT_DIR/scripts/install_qsm_tether_helper.sh"
  if [ -x "$helper" ] || [ "${KIOSK_INSTALL_QSM_TETHER:-1}" != "1" ]; then
    return 0
  fi
  if [ ! -f "$installer" ]; then
    warn "未找到主机数据网络安装脚本；Wi-Fi 仍可正常使用。"
    return 0
  fi
  if [ ! -t 0 ]; then
    warn "主机数据网络助手尚未安装；请运行 sudo sh scripts/install_qsm_tether_helper.sh。"
    return 0
  fi
  log "首次启用 QSM 数据网络需要一次管理员授权。"
  if sudo sh "$installer"; then
    log "QSM 数据网络备用路由已就绪。"
  else
    warn "未完成主机数据网络助手安装；本次将保留 Wi-Fi，应用其他功能不受影响。"
  fi
}

prepare_sim_fallback() {
  if [ "${KIOSK_QSM_TETHER:-1}" != "1" ]; then
    return 0
  fi

  log "检查 QSM 数据网络备用通道..."
  response="$(curl -fsS --max-time 35 -X POST "$BACKEND_URL/api/network/start-4g" 2>/dev/null || true)"
  if printf '%s' "$response" | grep -q '"ok":true'; then
    log "QSM 数据网络备用通道已就绪。"
  else
    warn "QSM 数据网络备用通道尚未就绪；Wi-Fi 和本地功能仍可继续使用。"
  fi

}

install_qsm_tether_helper_if_needed
start_backend_if_needed
sh "$ROOT_DIR/scripts/ensure_qsm_gateway.sh" || true
prepare_sim_fallback
if [ "$KIOSK_OFFLINE_AI" = "1" ]; then
  if [ -x "$ROOT_DIR/scripts/ensure_qsm_offline_ai.sh" ]; then
    sh "$ROOT_DIR/scripts/ensure_qsm_offline_ai.sh" || warn "QSM 离线模型暂未就绪；云端和安全规则仍可继续使用。"
  else
    warn "未找到离线模型检查脚本。"
  fi
  log "预热离线问询缓存..."
  if curl -sS --max-time 90 -X POST "$BACKEND_URL/api/ai/warm-local" \
    >"$RUN_DIR/local-ai-warmup.log" 2>&1; then
    log "离线问询缓存预热完成。"
  else
    warn "离线问询缓存预热未完成；应用仍会继续启动。"
  fi
fi
start_frontend_if_needed
prepare_kiosk_display
start_audio_relay_if_needed
prepare_chinese_input_method
start_touch_keyboard_if_needed
log "预热主机离线语音模型..."
if curl -sS --max-time 60 -X POST "$BACKEND_URL/api/audio/host/warmup" \
  >"$RUN_DIR/host-tts-warmup.log" 2>&1; then
  log "主机离线语音模型预热完成。"
else
  warn "主机离线语音模型预热未完成；应用仍会继续启动。"
fi

BROWSER="$(find_browser || true)"
if [ -z "$BROWSER" ]; then
  echo "未找到 Chromium/Chrome 浏览器，请先安装后再运行。" >&2
  exit 1
fi

KIOSK_APP_URL="$APP_URL"
if [ "$KIOSK_TOUCH_KEYBOARD" != "1" ]; then
  case "$KIOSK_APP_URL" in
    *\?*) KIOSK_APP_URL="${KIOSK_APP_URL}&touchKeyboard=0" ;;
    *) KIOSK_APP_URL="${KIOSK_APP_URL}?touchKeyboard=0" ;;
  esac
fi

log "全屏打开：$KIOSK_APP_URL"
if [ "${KIOSK_DRY_RUN:-0}" = "1" ]; then
  log "dry-run：将使用 $BROWSER 打开 kiosk 页面。"
  exit 0
fi

set -- "$BROWSER" \
  --kiosk "$KIOSK_APP_URL" \
  --start-fullscreen \
  --window-position=0,0 \
  --window-size="${KIOSK_WIDTH},${KIOSK_HEIGHT}" \
  --force-device-scale-factor="$KIOSK_SCALE" \
  --disable-pinch \
  --force-renderer-accessibility \
  --overscroll-history-navigation=0 \
  --no-first-run \
  --use-fake-ui-for-media-stream \
  --disable-session-crashed-bubble \
  --user-data-dir="$ROOT_DIR/data/chromium-kiosk"

if [ "$KIOSK_SAFE_GRAPHICS" = "1" ]; then
  set -- "$@" \
    --ozone-platform=x11 \
    --disable-gpu \
    --disable-accelerated-2d-canvas \
    --disable-background-networking \
    --disable-component-update \
    --disable-default-apps \
    --disable-extensions \
    --disable-sync \
    --metrics-recording-only \
    --disable-features=Vulkan,OptimizationGuideOnDeviceModel \
    --disable-dev-shm-usage
fi

start_browser "$@"
start_cleanup_guard
wait "$BROWSER_PID"
BROWSER_PID=""
