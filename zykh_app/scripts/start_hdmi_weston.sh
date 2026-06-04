#!/bin/sh

set -u

export XDG_RUNTIME_DIR=/run
export WAYLAND_DISPLAY=wayland-0
APP_DIR="${ZYKH_APP_DIR:-/userdata/zykh_app}"
RUN_DIR="$APP_DIR/runtime"
WESTON_CONFIG="$RUN_DIR/weston-hdmi.ini"

mkdir -p /run "$RUN_DIR"
echo 'output:HDMI-A-1:primary' > /tmp/.weston_drm.conf
cat > "$WESTON_CONFIG" <<EOF
[core]
idle-time=0

[shell]
locking=false
panel-position=none

[output]
name=HDMI-A-1
mode=current

[output]
name=LVDS-1
mode=off

[output]
name=DSI-1
mode=off
EOF

if [ "${FORCE_WESTON_RESTART:-0}" != "1" ] &&
   pidof weston >/dev/null 2>&1 &&
   [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]; then
  echo "Weston already running: $(pidof weston)"
  echo "HDMI status: $(cat /sys/class/drm/card0-HDMI-A-1/status 2>/dev/null)"
  echo "Wayland: $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY"
  exit 0
fi

pidof weston >/dev/null 2>&1 && kill $(pidof weston) 2>/dev/null
sleep 1
rm -f "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY.lock"

nohup weston --backend=drm-backend.so --tty=1 --idle-time=0 --debug --current-mode --config="$WESTON_CONFIG" \
  > /tmp/weston.log 2>&1 < /dev/null &

sleep 2
if pidof weston >/dev/null 2>&1; then
  echo "Weston started: $(pidof weston)"
  echo "HDMI status: $(cat /sys/class/drm/card0-HDMI-A-1/status 2>/dev/null)"
  echo "Wayland: $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY"
else
  echo "Weston failed, see /tmp/weston.log"
  tail -80 /tmp/weston.log 2>/dev/null
  exit 1
fi
