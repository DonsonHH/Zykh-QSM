#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
APP_URL="${APP_URL:-http://127.0.0.1:5173}"
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
KIOSK_WIDTH="${KIOSK_WIDTH:-1280}"
KIOSK_HEIGHT="${KIOSK_HEIGHT:-720}"
KIOSK_OUTPUT="${KIOSK_OUTPUT:-}"
KIOSK_SCALE="${KIOSK_SCALE:-1}"
KIOSK_SAFE_GRAPHICS="${KIOSK_SAFE_GRAPHICS:-1}"
KIOSK_RESTORE_RESOLUTION="${KIOSK_RESTORE_RESOLUTION:-1}"
KIOSK_BROWSER_LOG="${KIOSK_BROWSER_LOG:-file}"
KIOSK_AUDIO_RELAY="${KIOSK_AUDIO_RELAY:-1}"
KIOSK_RESTART_BACKEND="${KIOSK_RESTART_BACKEND:-1}"
RUN_DIR="$ROOT_DIR/data/run"
BROWSER_PID=""
AUDIO_RELAY_PID=""
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

stop_browser() {
  if [ -n "$BROWSER_PID" ] && kill -0 "$BROWSER_PID" >/dev/null 2>&1; then
    kill "$BROWSER_PID" >/dev/null 2>&1 || true
    wait "$BROWSER_PID" 2>/dev/null || true
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
  BACKEND_URL="$BACKEND_URL" sh "$ROOT_DIR/scripts/relay_host_audio_to_qsm.sh" >"$RUN_DIR/audio-relay.log" 2>&1 &
  AUDIO_RELAY_PID="$!"
  echo "$AUDIO_RELAY_PID" >"$RUN_DIR/audio-relay.pid"
  sleep 1
  if ! kill -0 "$AUDIO_RELAY_PID" >/dev/null 2>&1; then
    warn "本机音频实时转发未启动成功，日志：$RUN_DIR/audio-relay.log"
    AUDIO_RELAY_PID=""
  fi
}

stop_audio_relay() {
  if [ -n "$AUDIO_RELAY_PID" ] && kill -0 "$AUDIO_RELAY_PID" >/dev/null 2>&1; then
    kill "$AUDIO_RELAY_PID" >/dev/null 2>&1 || true
    wait "$AUDIO_RELAY_PID" 2>/dev/null || true
    log "本机音频转发已停止。"
  fi
}

on_exit() {
  status="$?"
  trap - EXIT INT TERM
  stop_browser
  stop_audio_relay
  restore_resolution
  exit "$status"
}

on_signal() {
  trap - EXIT INT TERM
  stop_browser
  stop_audio_relay
  restore_resolution
  exit 130
}

trap on_exit EXIT
trap on_signal INT TERM

backend_ready() {
  curl -fsS --max-time 1 "$BACKEND_URL/api/health" >/dev/null 2>&1
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
  if ! command -v pgrep >/dev/null 2>&1; then
    return 0
  fi

  stopped=0
  for pid in $(pgrep -f "uvicorn app.main.*--port $port" 2>/dev/null || true); do
    case "$pid" in
      ''|*[!0-9]*) continue ;;
    esac
    cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
    case "$cwd" in
      "$ROOT_DIR/backend"|"$ROOT_DIR/backend/"*)
        log "停止旧后端进程 PID $pid，以加载最新配置..."
        kill "$pid" >/dev/null 2>&1 || true
        stopped=1
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
  curl -fsS --max-time 1 "$APP_URL" >/dev/null 2>&1
}

wait_for_backend() {
  count=0
  while [ "$count" -lt 30 ]; do
    if backend_ready; then
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

  if backend_ready; then
    log "后端已运行：$BACKEND_URL"
    if [ "$KIOSK_RESTART_BACKEND" = "1" ]; then
      warn "检测到 8000 端口仍有外部后端进程；如需加载最新配置，请先停止该进程后重新运行脚本。"
    fi
    return 0
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

  log "启动前端服务..."
  nohup sh "$ROOT_DIR/scripts/start_frontend.sh" >"$RUN_DIR/frontend.log" 2>&1 &
  echo "$!" >"$RUN_DIR/frontend.pid"

  if wait_for_frontend; then
    log "前端启动完成：$APP_URL"
  else
    warn "前端未在预期时间内就绪，日志：$RUN_DIR/frontend.log"
  fi
}

set_kiosk_resolution() {
  if [ "${KIOSK_SKIP_RESOLUTION:-0}" = "1" ]; then
    log "跳过分辨率切换。"
    return 0
  fi

  if ! command -v xrandr >/dev/null 2>&1; then
    warn "未找到 xrandr，无法自动切换分辨率。"
    return 0
  fi

  output="$KIOSK_OUTPUT"
  if [ -z "$output" ]; then
    output="$(xrandr --query | awk '/ connected/{print $1; exit}')"
  fi

  if [ -z "$output" ]; then
    warn "未检测到可用显示输出，跳过分辨率切换。"
    return 0
  fi

  RESTORE_OUTPUT="$output"
  RESTORE_MODE="$(current_mode_for_output "$output" || true)"

  mode="${KIOSK_WIDTH}x${KIOSK_HEIGHT}"
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

start_backend_if_needed
sh "$ROOT_DIR/scripts/ensure_qsm_gateway.sh" || true
start_frontend_if_needed
set_kiosk_resolution
start_audio_relay_if_needed

BROWSER="$(find_browser || true)"
if [ -z "$BROWSER" ]; then
  echo "未找到 Chromium/Chrome 浏览器，请先安装后再运行。" >&2
  exit 1
fi

log "全屏打开：$APP_URL"
if [ "${KIOSK_DRY_RUN:-0}" = "1" ]; then
  log "dry-run：将使用 $BROWSER 打开 kiosk 页面。"
  exit 0
fi

set -- "$BROWSER" \
  --kiosk "$APP_URL" \
  --start-fullscreen \
  --window-position=0,0 \
  --window-size="${KIOSK_WIDTH},${KIOSK_HEIGHT}" \
  --force-device-scale-factor="$KIOSK_SCALE" \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --no-first-run \
  --use-fake-ui-for-media-stream \
  --disable-session-crashed-bubble \
  --user-data-dir="$ROOT_DIR/data/chromium-kiosk"

if [ "$KIOSK_SAFE_GRAPHICS" = "1" ]; then
  set -- "$@" \
    --ozone-platform=x11 \
    --disable-gpu \
    --disable-gpu-compositing \
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
wait "$BROWSER_PID"
BROWSER_PID=""
