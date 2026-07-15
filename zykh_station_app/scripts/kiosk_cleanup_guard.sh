#!/usr/bin/env sh

# Runs outside the launcher process so display/audio cleanup still happens when
# the terminal or launcher is killed before its EXIT trap can run.
set -u

PARENT_PID="${1:-}"
PARENT_START="${2:-}"
BROWSER_PID="${3:-}"
AUDIO_PID="${4:-}"
AUDIO_PROCESS_GROUP="${5:-0}"
BACKEND_URL="${6:-http://127.0.0.1:8000}"
RESTORE_OUTPUT="${7:-}"
RESTORE_MODE="${8:-}"
RESTORE_ENABLED="${9:-1}"
DONE_FILE="${10:-}"

log() {
  printf '[kiosk-guard] %s\n' "$*"
}

process_is_original_parent() {
  [ -n "$PARENT_PID" ] || return 1
  kill -0 "$PARENT_PID" >/dev/null 2>&1 || return 1
  [ -r "/proc/$PARENT_PID/stat" ] || return 0
  current_start="$(awk '{print $22}' "/proc/$PARENT_PID/stat" 2>/dev/null || true)"
  [ -z "$PARENT_START" ] || [ "$current_start" = "$PARENT_START" ]
}

terminate_process() {
  pid="$1"
  process_group="$2"
  case "$pid" in
    ''|*[!0-9]*) return 0 ;;
  esac
  kill -0 "$pid" >/dev/null 2>&1 || return 0

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
}

while process_is_original_parent; do
  sleep 0.5
done

if [ -n "$DONE_FILE" ] && [ -e "$DONE_FILE" ]; then
  rm -f "$DONE_FILE"
  exit 0
fi

log "检测到启动任务异常退出，开始兜底清理。"
terminate_process "$BROWSER_PID" "0"
terminate_process "$AUDIO_PID" "$AUDIO_PROCESS_GROUP"
curl -sS --max-time 2 -X POST "$BACKEND_URL/api/audio/stream/stop" >/dev/null 2>&1 || true
log "本机音频转发已停止。"

if [ "$RESTORE_ENABLED" = "1" ] && [ -n "$RESTORE_OUTPUT" ] && [ -n "$RESTORE_MODE" ] && command -v xrandr >/dev/null 2>&1; then
  if xrandr --output "$RESTORE_OUTPUT" --mode "$RESTORE_MODE" >/dev/null 2>&1; then
    log "显示输出 $RESTORE_OUTPUT 已恢复到 $RESTORE_MODE。"
  else
    log "WARN: 无法恢复显示输出 $RESTORE_OUTPUT 到 $RESTORE_MODE。"
  fi
fi

rm -f "$DONE_FILE"
