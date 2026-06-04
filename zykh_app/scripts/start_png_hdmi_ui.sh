#!/bin/sh

set -u

APP_DIR="${ZYKH_APP_DIR:-/userdata/zykh_app}"
RUN_DIR="$APP_DIR/runtime"
SCREEN="${1:-home}"
SRC="$APP_DIR/native/screens/$SCREEN.png"
FRAME="$RUN_DIR/native-screen-00000.png"

mkdir -p "$RUN_DIR"

if ! gst-inspect-1.0 pngdec >/dev/null 2>&1; then
  echo "pngdec not found; PNG HDMI UI cannot start"
  exit 1
fi

if [ ! -f "$SRC" ]; then
  echo "screen not found: $SCREEN"
  echo "available:"
  ls "$APP_DIR/native/screens" 2>/dev/null | sed 's/\.png$//' || true
  exit 1
fi

sh "$APP_DIR/scripts/start_hdmi_weston.sh" || exit 1
rm -f "$FRAME"
ln "$SRC" "$FRAME" 2>/dev/null || cp "$SRC" "$FRAME"

if [ -f "$RUN_DIR/native-ui-gst.pid" ]; then
  kill "$(cat "$RUN_DIR/native-ui-gst.pid")" 2>/dev/null || true
fi
pidof gst-launch-1.0 >/dev/null 2>&1 && kill $(pidof gst-launch-1.0) 2>/dev/null || true

export XDG_RUNTIME_DIR=/run
export WAYLAND_DISPLAY=wayland-0
nohup gst-launch-1.0 -q \
  multifilesrc location="$RUN_DIR/native-screen-%05d.png" start-index=0 stop-index=0 loop=true caps="image/png,framerate=(fraction)1/1" \
  ! pngdec \
  ! identity sleep-time=1000000 \
  ! videoconvert \
  ! videoscale \
  ! video/x-raw,width=1024,height=600 \
  ! waylandsink sync=false fullscreen=true \
  > "$RUN_DIR/png-ui-gst.log" 2>&1 < /dev/null &
echo $! > "$RUN_DIR/native-ui-gst.pid"

sleep 1

echo "PNG HDMI UI started"
echo "screen: $SCREEN"
echo "source: $SRC"
echo "gstreamer pid: $(cat "$RUN_DIR/native-ui-gst.pid")"
