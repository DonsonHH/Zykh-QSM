#!/bin/sh
set -eu

PROJECT_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
FIXTURE="$PROJECT_ROOT/scripts/tests/fixtures/kiosk_fake_command.sh"
TMP_ROOT="$(mktemp -d)"
TEST_ROOT="$TMP_ROOT/station"
FAKE_BIN="$TMP_ROOT/bin"
LOG_FILE="$TMP_ROOT/launch.log"
LAUNCH_PID=""

cleanup() {
  trap - EXIT INT TERM
  if [ -n "$LAUNCH_PID" ] && kill -0 "$LAUNCH_PID" >/dev/null 2>&1; then
    kill -KILL "$LAUNCH_PID" >/dev/null 2>&1 || true
  fi
  for event_file in "$TMP_ROOT/browser.events" "$TMP_ROOT/relay.events"; do
    [ -f "$event_file" ] || continue
    awk '$1 == "started" { print $2 }' "$event_file" | while read -r pid; do
      kill -KILL "$pid" >/dev/null 2>&1 || true
    done
  done
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT INT TERM

mkdir -p "$TEST_ROOT/scripts" "$TEST_ROOT/data/run" "$FAKE_BIN"
cp "$PROJECT_ROOT/scripts/launch_kiosk.sh" "$TEST_ROOT/scripts/launch_kiosk.sh"
cp "$FIXTURE" "$TEST_ROOT/scripts/relay_host_audio_to_qsm.sh"
cp "$FIXTURE" "$TEST_ROOT/scripts/ensure_qsm_gateway.sh"
chmod +x "$TEST_ROOT/scripts/"*.sh

for command in curl xrandr chromium; do
  ln -s "$FIXTURE" "$FAKE_BIN/$command"
done

export FAKE_XRANDR_EVENTS="$TMP_ROOT/xrandr.events"
export FAKE_BROWSER_EVENTS="$TMP_ROOT/browser.events"
export FAKE_RELAY_EVENTS="$TMP_ROOT/relay.events"

assert_contains() {
  pattern="$1"
  file="$2"
  label="$3"
  if grep -q -- "$pattern" "$file" 2>/dev/null; then
    return 0
  fi
  printf 'FAIL: %s\n' "$label" >&2
  printf '%s\n' "--- $file ---" >&2
  sed -n '1,160p' "$file" >&2 2>/dev/null || true
  exit 1
}

PATH="$FAKE_BIN:$PATH" \
  KIOSK_BROWSER_LOG=terminal \
  KIOSK_RESTART_BACKEND=0 \
  sh "$TEST_ROOT/scripts/launch_kiosk.sh" >"$LOG_FILE" 2>&1 &
LAUNCH_PID="$!"

attempt=0
while [ "$attempt" -lt 50 ]; do
  if [ -s "$FAKE_BROWSER_EVENTS" ] && [ -s "$FAKE_RELAY_EVENTS" ]; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 0.1
done

kill -HUP "$LAUNCH_PID"
wait "$LAUNCH_PID" 2>/dev/null || true
LAUNCH_PID=""

assert_contains '--output DP-1 --mode 1280x720' "$FAKE_XRANDR_EVENTS" "kiosk resolution was not applied"
assert_contains '--output DP-1 --mode 1920x1080' "$FAKE_XRANDR_EVENTS" "original resolution was not restored after SIGHUP"
assert_contains '^stopped ' "$FAKE_RELAY_EVENTS" "audio relay was not stopped after SIGHUP"
assert_contains '\[kiosk\] 本机音频转发已停止。' "$LOG_FILE" "audio cleanup was not reported"
assert_contains '\[kiosk\] 显示输出 DP-1 已恢复到 1920x1080。' "$LOG_FILE" "display cleanup was not reported"

printf 'launch_kiosk cleanup: OK\n'
