#!/bin/sh
set -u

name="$(basename "$0")"

case "$name" in
  curl)
    case "$*" in
      *'/api/health'*)
        if [ -n "${FAKE_BACKEND_STATE:-}" ] && [ -f "$FAKE_BACKEND_STATE" ]; then
          state=$(cat "$FAKE_BACKEND_STATE" 2>/dev/null || true)
          if [ "$state" != "healthy" ]; then
            exit 22
          fi
        fi
        printf '%s\n' '{"ok":true}'
        ;;
      *'/src/styles/app.css'*) printf '%s\n' 'const __vite__css = "body{}";' ;;
      *'/api/medicines/slot-08-huoxiang-zhengqi'*)
        printf '%s\n' '{"indications":"test","dosage":"test","guidance_source":"verified"}'
        ;;
    esac
    exit 0
    ;;
  xrandr)
    if [ "${1:-}" = "--query" ]; then
      printf '%s\n' \
        'DP-1 connected primary 1920x1080+0+0' \
        '   1920x1080     60.00*+' \
        '   1280x720      60.00'
      exit 0
    fi
    printf '%s\n' "$*" >>"$FAKE_XRANDR_EVENTS"
    exit 0
    ;;
  chromium)
    printf '%s\n' "args $*" >>"$FAKE_BROWSER_EVENTS"
    printf '%s\n' "started $$" >>"$FAKE_BROWSER_EVENTS"
    trap 'printf "%s\n" "stopped $$" >>"$FAKE_BROWSER_EVENTS"; exit 0' HUP INT QUIT TERM
    while :; do
      sleep 1
    done
    ;;
  relay_host_audio_to_qsm.sh)
    printf '%s\n' "started $$" >>"$FAKE_RELAY_EVENTS"
    trap 'printf "%s\n" "stopped $$" >>"$FAKE_RELAY_EVENTS"; exit 0' HUP INT QUIT TERM
    while :; do
      sleep 1
    done
    ;;
  ensure_qsm_gateway.sh)
    exit 0
    ;;
  start_backend.sh)
    printf '%s\n' "started $$" >>"$FAKE_BACKEND_EVENTS"
    printf '%s\n' 'healthy' >"$FAKE_BACKEND_STATE"
    trap 'printf "%s\n" "stopped $$" >>"$FAKE_BACKEND_EVENTS"; exit 0' HUP INT QUIT TERM
    while :; do
      sleep 1
    done
    ;;
  *)
    printf 'unexpected fake command: %s\n' "$name" >&2
    exit 1
    ;;
esac
