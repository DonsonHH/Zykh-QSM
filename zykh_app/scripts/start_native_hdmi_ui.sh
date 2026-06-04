#!/bin/sh

set -u

APP_DIR="${ZYKH_APP_DIR:-/userdata/zykh_app}"
RUN_DIR="$APP_DIR/runtime"
FONT_DIR="$APP_DIR/fonts"
FRAME_PATTERN="$RUN_DIR/native-home-%05d.svg"
FRAME_FILE="$RUN_DIR/native-home-00000.svg"

mkdir -p "$RUN_DIR"

if ! gst-inspect-1.0 gdkpixbufdec >/dev/null 2>&1; then
  echo "gdkpixbufdec not found; native SVG UI cannot start"
  exit 1
fi

cat > "$RUN_DIR/fonts.conf" <<EOF
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>$FONT_DIR</dir>
  <dir>/usr/share/fonts</dir>
  <cachedir>$RUN_DIR/fontcache</cachedir>
</fontconfig>
EOF

export FONTCONFIG_FILE="$RUN_DIR/fonts.conf"
export FONTCONFIG_PATH="$RUN_DIR"
mkdir -p "$RUN_DIR/fontcache"
if [ -d "$FONT_DIR" ]; then
  fc-cache -f "$FONT_DIR" >/dev/null 2>&1 || true
fi

sh "$APP_DIR/scripts/start_hdmi_weston.sh" || exit 1

ZYKH_APP_DIR="$APP_DIR" \
ZYKH_NATIVE_RUNTIME="$RUN_DIR" \
ZYKH_NATIVE_FRAME="$FRAME_FILE" \
perl "$APP_DIR/native_home.pl" >/dev/null 2>&1 || {
  echo "render native frame failed"
  exit 1
}

if [ -f "$RUN_DIR/native-render.pid" ]; then
  kill "$(cat "$RUN_DIR/native-render.pid")" 2>/dev/null || true
fi
if [ -f "$RUN_DIR/native-ui-gst.pid" ]; then
  kill "$(cat "$RUN_DIR/native-ui-gst.pid")" 2>/dev/null || true
fi

(
  while true; do
    ZYKH_APP_DIR="$APP_DIR" \
    ZYKH_NATIVE_RUNTIME="$RUN_DIR" \
    ZYKH_NATIVE_FRAME="$FRAME_FILE" \
    perl "$APP_DIR/native_home.pl" >/dev/null 2>&1
    sleep 1
  done
) > "$RUN_DIR/native-render.log" 2>&1 &
echo $! > "$RUN_DIR/native-render.pid"

export XDG_RUNTIME_DIR=/run
export WAYLAND_DISPLAY=wayland-0
nohup gst-launch-1.0 -q \
  multifilesrc location="$FRAME_PATTERN" start-index=0 stop-index=0 loop=true caps="image/svg+xml,framerate=1/1" \
  ! gdkpixbufdec \
  ! videoconvert \
  ! videoscale \
  ! video/x-raw,width=1024,height=600 \
  ! waylandsink sync=false fullscreen=true \
  > "$RUN_DIR/native-ui-gst.log" 2>&1 < /dev/null &
echo $! > "$RUN_DIR/native-ui-gst.pid"

sleep 1

echo "Native HDMI UI started"
echo "renderer pid: $(cat "$RUN_DIR/native-render.pid")"
echo "gstreamer pid: $(cat "$RUN_DIR/native-ui-gst.pid")"
echo "frame: $FRAME_FILE"
