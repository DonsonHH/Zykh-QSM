#!/bin/sh
set -eu

PROJECT_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
TEST_ROOT="$(mktemp -d)"
FAKE_BIN="$TEST_ROOT/bin"
NPM_EVENTS="$TEST_ROOT/npm.events"

cleanup() {
  rm -rf "$TEST_ROOT"
}
trap cleanup EXIT INT TERM

mkdir -p "$FAKE_BIN"
cat >"$FAKE_BIN/npm" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >>"$NPM_EVENTS"
exit 0
EOF
chmod +x "$FAKE_BIN/npm"

PATH="$FAKE_BIN:$PATH" \
NPM_EVENTS="$NPM_EVENTS" \
ZYKH_FRONTEND_HOST=127.0.0.1 \
ZYKH_FRONTEND_PORT=5179 \
  sh "$PROJECT_ROOT/scripts/start_frontend.sh"

grep -qx 'run build' "$NPM_EVENTS" || {
  printf 'FAIL: production assets were not built before frontend startup\n' >&2
  exit 1
}
grep -qx 'run preview -- --host 127.0.0.1 --port 5179' "$NPM_EVENTS" || {
  printf 'FAIL: frontend was not started through the production preview server\n' >&2
  exit 1
}
if grep -q 'run dev' "$NPM_EVENTS"; then
  printf 'FAIL: kiosk frontend returned to Vite development mode\n' >&2
  exit 1
fi

printf 'frontend production startup: OK\n'
