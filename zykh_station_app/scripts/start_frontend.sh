#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR/frontend"

FRONTEND_HOST="${ZYKH_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${ZYKH_FRONTEND_PORT:-5173}"

npm run build
exec npm run preview -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
