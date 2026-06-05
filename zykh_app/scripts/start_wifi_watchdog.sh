#!/bin/sh

set -u

APP_DIR="${ZYKH_APP_DIR:-/userdata/zykh_app}"
WIFI_SCRIPT="${WIFI_SCRIPT:-/userdata/medical_assistant/scripts/start_wifi.sh}"
INTERVAL="${WIFI_CHECK_INTERVAL:-20}"
RUN_DIR=/var/run/wpa_supplicant
LOG="${WIFI_WATCHDOG_LOG:-$APP_DIR/data/wifi-watchdog.log}"

mkdir -p "$(dirname "$LOG")"

echo "===== Wi-Fi watchdog start: interval=${INTERVAL}s =====" >> "$LOG"

wifi_ok() {
  for dev in wlan0 wlan1; do
    if wpa_cli -i "$dev" -p "$RUN_DIR" status 2>/dev/null | grep '^wpa_state=COMPLETED' >/dev/null 2>&1; then
      ping -c 1 -W 2 223.5.5.5 >/dev/null 2>&1 && return 0
      ping -c 1 -W 2 192.168.137.1 >/dev/null 2>&1 && return 0
    fi
  done
  return 1
}

while true; do
  if wifi_ok; then
    sleep "$INTERVAL"
    continue
  fi

  echo "$(date '+%Y-%m-%d %H:%M:%S') Wi-Fi disconnected, reconnecting..." >> "$LOG"
  sh "$WIFI_SCRIPT" >> "$LOG" 2>&1 || true
  sleep "$INTERVAL"
done
