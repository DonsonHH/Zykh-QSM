#!/bin/sh

set -u

APP_DIR="${ZYKH_APP_DIR:-/userdata/zykh_app}"
RUN_DIR="$APP_DIR/runtime"

if [ -f "$RUN_DIR/go-ui.pid" ]; then
  kill "$(cat "$RUN_DIR/go-ui.pid")" 2>/dev/null || true
  rm -f "$RUN_DIR/go-ui.pid"
fi

pidof zykh-go-ui >/dev/null 2>&1 && kill $(pidof zykh-go-ui) 2>/dev/null || true

echo "Go HDMI UI stopped"
