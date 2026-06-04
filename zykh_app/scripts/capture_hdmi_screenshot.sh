#!/bin/sh

set -u

APP_DIR="${ZYKH_APP_DIR:-/userdata/zykh_app}"
RUN_DIR="$APP_DIR/runtime"

mkdir -p "$RUN_DIR"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"

cd "$RUN_DIR"
rm -f wayland-screenshot-*.png screenshooter.err

weston-screenshooter 2>screenshooter.err || {
  echo "weston-screenshooter failed"
  cat screenshooter.err 2>/dev/null || true
  exit 1
}

SHOT="$(ls -t wayland-screenshot-*.png 2>/dev/null | head -1)"
if [ -z "$SHOT" ]; then
  echo "screenshot file not found"
  cat screenshooter.err 2>/dev/null || true
  exit 1
fi

cp "$SHOT" hdmi-current.png
echo "$RUN_DIR/hdmi-current.png"
