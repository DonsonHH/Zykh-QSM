#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

sh "$ROOT_DIR/scripts/ensure_qsm_gateway.sh" || true

sh "$ROOT_DIR/scripts/start_backend.sh" &
BACKEND_PID="$!"

cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

sh "$ROOT_DIR/scripts/start_frontend.sh"
