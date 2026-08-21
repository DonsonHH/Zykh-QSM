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
    kill -TERM "$LAUNCH_PID" >/dev/null 2>&1 || true
    wait "$LAUNCH_PID" 2>/dev/null || true
  fi
  if [ -f "$TMP_ROOT/backend.events" ]; then
    awk '$1 == "started" { print $2 }' "$TMP_ROOT/backend.events" | while read -r pid; do
      kill -TERM "$pid" >/dev/null 2>&1 || true
    done
  fi
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT INT TERM

mkdir -p "$TEST_ROOT/scripts" "$TEST_ROOT/data/run" "$FAKE_BIN"
cp "$PROJECT_ROOT/scripts/launch_kiosk.sh" "$TEST_ROOT/scripts/launch_kiosk.sh"
cp "$PROJECT_ROOT/scripts/kiosk_cleanup_guard.sh" "$TEST_ROOT/scripts/kiosk_cleanup_guard.sh"
for script in relay_host_audio_to_qsm.sh ensure_qsm_gateway.sh start_backend.sh; do
  cp "$FIXTURE" "$TEST_ROOT/scripts/$script"
  chmod +x "$TEST_ROOT/scripts/$script"
done
for command in curl xrandr chromium; do
  ln -s "$FIXTURE" "$FAKE_BIN/$command"
done

export FAKE_XRANDR_EVENTS="$TMP_ROOT/xrandr.events"
export FAKE_BROWSER_EVENTS="$TMP_ROOT/browser.events"
export FAKE_RELAY_EVENTS="$TMP_ROOT/relay.events"
export FAKE_BACKEND_EVENTS="$TMP_ROOT/backend.events"
export FAKE_BACKEND_STATE="$TMP_ROOT/backend.state"
printf '%s\n' healthy >"$FAKE_BACKEND_STATE"

PATH="$FAKE_BIN:$PATH" \
  KIOSK_AUDIO_RELAY=0 \
  KIOSK_BROWSER_LOG=terminal \
  KIOSK_RESTART_BACKEND=0 \
  KIOSK_TOUCH_KEYBOARD=0 \
  KIOSK_BACKEND_HEALTH_INTERVAL_SECONDS=0.1 \
  sh "$TEST_ROOT/scripts/launch_kiosk.sh" >"$LOG_FILE" 2>&1 &
LAUNCH_PID="$!"

attempt=0
while [ "$attempt" -lt 50 ] && [ ! -s "$FAKE_BROWSER_EVENTS" ]; do
  attempt=$((attempt + 1))
  sleep 0.1
done
if [ ! -s "$FAKE_BROWSER_EVENTS" ]; then
  printf 'FAIL: kiosk browser did not start\n' >&2
  sed -n '1,200p' "$LOG_FILE" >&2 || true
  exit 1
fi

printf '%s\n' failed >"$FAKE_BACKEND_STATE"
attempt=0
while [ "$attempt" -lt 40 ] && [ ! -s "$FAKE_BACKEND_EVENTS" ]; do
  attempt=$((attempt + 1))
  sleep 0.1
done

if ! grep -q '^started ' "$FAKE_BACKEND_EVENTS" 2>/dev/null; then
  printf 'FAIL: kiosk left the frontend running after its backend became unavailable\n' >&2
  sed -n '1,220p' "$LOG_FILE" >&2 || true
  exit 1
fi
if [ "$(cat "$FAKE_BACKEND_STATE")" != "healthy" ]; then
  printf 'FAIL: supervised backend did not restore health\n' >&2
  exit 1
fi

kill -TERM "$LAUNCH_PID" >/dev/null 2>&1 || true
wait "$LAUNCH_PID" 2>/dev/null || true
LAUNCH_PID=""
printf 'launch_kiosk backend supervision: OK\n'
