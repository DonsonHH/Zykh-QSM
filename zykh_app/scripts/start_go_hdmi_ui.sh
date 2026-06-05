#!/bin/sh

APP_DIR=/userdata/zykh_app
BIN=$APP_DIR/bin/zykh-go-ui
LOG=$APP_DIR/data/go-ui.log

mkdir -p $APP_DIR/data

if [ -x "$APP_DIR/scripts/ensure_wifi_watchdog.sh" ]; then
    sh "$APP_DIR/scripts/ensure_wifi_watchdog.sh" >/dev/null 2>&1 || true
fi

echo "Starting desktop display service..."
killall zykh-go-ui 2>/dev/null || true
killall gst-launch-1.0 2>/dev/null || true
killall glmark2-es2-way 2>/dev/null || true
killall glmark2-es2-drm 2>/dev/null || true
killall weston-simple-egl 2>/dev/null || true
killall weston-simple-shm 2>/dev/null || true
FORCE_WESTON_RESTART=1 sh "$APP_DIR/scripts/start_hdmi_weston.sh" || exit 1

export XDG_RUNTIME_DIR=/run
export WAYLAND_DISPLAY=wayland-0
export TZ=CST-8
export ZYKH_UI_WIDTH=1024
export ZYKH_UI_HEIGHT=600
export ZYKH_FB=/dev/fb0
export ZYKH_DRM_CARD=/dev/dri/card0
export ZYKH_RENDER_TARGET=wayland
export ZYKH_START_PAGE="${ZYKH_START_PAGE:-home}"
export ZYKH_TOUCH_EVENT=/dev/input/event4
export ZYKH_APP_DIR=/userdata/zykh_app
export ZYKH_API_BASE=http://127.0.0.1:8080
export ZYKH_CAMERA_WIDTH="${ZYKH_CAMERA_WIDTH:-424}"
export ZYKH_CAMERA_HEIGHT="${ZYKH_CAMERA_HEIGHT:-240}"
export ZYKH_CAMERA_FPS="${ZYKH_CAMERA_FPS:-20}"
export ZYKH_CAMERA_QUALITY="${ZYKH_CAMERA_QUALITY:-60}"

echo "Starting Go HDMI UI..."
nohup env \
  ZYKH_UI_WIDTH=$ZYKH_UI_WIDTH \
  ZYKH_UI_HEIGHT=$ZYKH_UI_HEIGHT \
  XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR \
  WAYLAND_DISPLAY=$WAYLAND_DISPLAY \
  TZ=$TZ \
  ZYKH_FB=$ZYKH_FB \
  ZYKH_DRM_CARD=$ZYKH_DRM_CARD \
  ZYKH_RENDER_TARGET=$ZYKH_RENDER_TARGET \
  ZYKH_START_PAGE=$ZYKH_START_PAGE \
  ZYKH_TOUCH_EVENT=$ZYKH_TOUCH_EVENT \
  ZYKH_APP_DIR=$ZYKH_APP_DIR \
  ZYKH_API_BASE=$ZYKH_API_BASE \
  ZYKH_CAMERA_WIDTH=$ZYKH_CAMERA_WIDTH \
  ZYKH_CAMERA_HEIGHT=$ZYKH_CAMERA_HEIGHT \
  ZYKH_CAMERA_FPS=$ZYKH_CAMERA_FPS \
  ZYKH_CAMERA_QUALITY=$ZYKH_CAMERA_QUALITY \
  $BIN > $LOG 2>&1 < /dev/null &

sleep 1

PID=$(pidof zykh-go-ui)

if [ -n "$PID" ]; then
    echo "Go HDMI UI started"
    echo "pid: $PID"
    echo "render: $ZYKH_RENDER_TARGET"
    echo "page: $ZYKH_START_PAGE"
    echo "wayland: $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY"
    echo "touch: $ZYKH_TOUCH_EVENT"
    echo "camera: ${ZYKH_CAMERA_WIDTH}x${ZYKH_CAMERA_HEIGHT}@${ZYKH_CAMERA_FPS}"
else
    echo "Go HDMI UI failed"
    cat $LOG 2>/dev/null
fi
