#!/bin/sh

set -u

APP_DIR="${ZYKH_APP_DIR:-/userdata/zykh_app}"
RUN_DIR="$APP_DIR/runtime"

for pidfile in "$RUN_DIR/native-ui-gst.pid" "$RUN_DIR/native-render.pid"; do
  if [ -f "$pidfile" ]; then
    kill "$(cat "$pidfile")" 2>/dev/null || true
    rm -f "$pidfile"
  fi
done

pidof gst-launch-1.0 >/dev/null 2>&1 && kill $(pidof gst-launch-1.0) 2>/dev/null || true

echo "Native HDMI UI stopped"
