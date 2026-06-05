#!/bin/sh

set -u

RUN_DIR=/var/run/wpa_supplicant
CONF=/userdata/wpa_zykh.conf
PROFILE_FILE="${WIFI_PROFILE_FILE:-/userdata/wifi_profiles.conf}"
SKIP_SSIDS="${WIFI_SKIP_SSIDS:-964}"
TMP_PROFILES=/tmp/zykh_wifi_profiles.txt
TMP_ORDERED=/tmp/zykh_wifi_profiles_ordered.txt
SCAN_FILE=/tmp/zykh_wifi_scan.txt

mkdir -p "$RUN_DIR"
: > "$TMP_PROFILES"

add_profile() {
  ssid="$1"
  pass="$2"
  [ -z "$ssid" ] && return
  [ -z "$pass" ] && return
  for skip in $SKIP_SSIDS; do
    [ "$ssid" = "$skip" ] && return
  done
  printf '%s|%s\n' "$ssid" "$pass" >> "$TMP_PROFILES"
}

if [ -n "${WIFI_SSID:-}" ] && [ -n "${WIFI_PASSWORD:-}" ]; then
  add_profile "$WIFI_SSID" "$WIFI_PASSWORD"
fi

if [ -s "$PROFILE_FILE" ]; then
  while IFS='|' read -r ssid pass; do
    case "$ssid" in ''|\#*) continue ;; esac
    add_profile "$ssid" "$pass"
  done < "$PROFILE_FILE"
fi

if [ -s /userdata/wifi_ssid.txt ] && [ -s /userdata/wifi_password.txt ]; then
  add_profile "$(cat /userdata/wifi_ssid.txt)" "$(cat /userdata/wifi_password.txt)"
fi

if [ ! -s "$TMP_PROFILES" ]; then
  echo "Missing Wi-Fi profile. Set WIFI_SSID/WIFI_PASSWORD or write $PROFILE_FILE"
  exit 1
fi

echo "===== Scan Wi-Fi ====="
: > "$SCAN_FILE"
for dev in wlan0 wlan1; do
  if ifconfig "$dev" >/dev/null 2>&1; then
    ifconfig "$dev" up 2>/dev/null || true
    iw dev "$dev" scan 2>/dev/null >> "$SCAN_FILE" || true
  fi
done

: > "$TMP_ORDERED"
while IFS='|' read -r ssid pass; do
  [ -z "$ssid" ] && continue
  if grep -F "SSID: $ssid" "$SCAN_FILE" >/dev/null 2>&1; then
    printf '%s|%s\n' "$ssid" "$pass" >> "$TMP_ORDERED"
  fi
done < "$TMP_PROFILES"
while IFS='|' read -r ssid pass; do
  [ -z "$ssid" ] && continue
  grep -F -x "$ssid|$pass" "$TMP_ORDERED" >/dev/null 2>&1 || printf '%s|%s\n' "$ssid" "$pass" >> "$TMP_ORDERED"
done < "$TMP_PROFILES"

connect_profile() {
  SSID="$1"
  PASSWORD="$2"
  echo "===== Restart Wi-Fi: $SSID ====="

  killall dhcpcd 2>/dev/null || true
  killall udhcpc 2>/dev/null || true
  killall wpa_supplicant 2>/dev/null || true
  sleep 1

  if command -v wpa_passphrase >/dev/null 2>&1; then
    wpa_passphrase "$SSID" "$PASSWORD" > "$CONF"
  else
    cat > "$CONF" <<EOF
network={
    ssid="$SSID"
    psk="$PASSWORD"
    key_mgmt=WPA-PSK
}
EOF
  fi
  chmod 600 "$CONF"

  IFACE=""
  for dev in wlan0 wlan1; do
    if ifconfig "$dev" >/dev/null 2>&1; then
      ifconfig "$dev" up 2>/dev/null || true
      if iw dev "$dev" scan 2>/dev/null | grep -F "SSID: $SSID" >/dev/null 2>&1; then
        IFACE="$dev"
        break
      fi
      [ -z "$IFACE" ] && IFACE="$dev"
    fi
  done

  if [ -z "$IFACE" ]; then
    echo "No wlan interface found"
    return 1
  fi

  echo "interface=$IFACE"
  rm -f "$RUN_DIR/$IFACE" 2>/dev/null || true
  wpa_supplicant -B -i "$IFACE" -c "$CONF" -C "$RUN_DIR"

  echo "===== Wait for Wi-Fi connection ====="
  i=0
  state=""
  while [ "$i" -lt 25 ]; do
    state=$(wpa_cli -i "$IFACE" -p "$RUN_DIR" status 2>/dev/null | grep '^wpa_state=' | cut -d= -f2)
    echo "wpa_state=$state"
    [ "$state" = "COMPLETED" ] && break
    wpa_cli -i "$IFACE" -p "$RUN_DIR" reconnect >/dev/null 2>&1 || true
    sleep 2
    i=$((i + 1))
  done
  [ "$state" = "COMPLETED" ] || return 1

  echo "===== Request DHCP ====="
  timeout 45 udhcpc -i "$IFACE" -q -n -t 10 -T 3 || timeout 45 udhcpc -i "$IFACE" -q -n -t 10 -T 3 || true

  echo "===== Fix route and DNS ====="
  for _ in 1 2 3 4 5; do
    route del default 2>/dev/null || break
  done
  IP=$(ifconfig "$IFACE" 2>/dev/null | sed -n 's/.*inet addr:\([0-9.]*\).*/\1/p' | head -1)
  [ -z "$IP" ] && IP=$(wpa_cli -i "$IFACE" -p "$RUN_DIR" status 2>/dev/null | grep '^ip_address=' | cut -d= -f2)
  DNS_GW=$(sed -n 's/^nameserver[[:space:]]\+\([0-9.]*\).*/\1/p' /tmp/resolv.conf /etc/resolv.conf 2>/dev/null | head -1)
  GW1=$(echo "$IP" | sed 's/\.[0-9]*$/.1/')
  GW193=$(echo "$IP" | sed 's/\.[0-9]*$/.193/')
  GW=""
  for cand in "$DNS_GW" "$GW1" "$GW193"; do
    [ -z "$cand" ] && continue
    route del default 2>/dev/null || true
    route add default gw "$cand" dev "$IFACE" 2>/dev/null || true
    if ping -c 1 -W 2 223.5.5.5 >/dev/null 2>&1; then
      GW="$cand"
      break
    fi
  done
  printf 'nameserver 223.5.5.5\nnameserver 114.114.114.114\nnameserver 8.8.8.8\n' > /tmp/resolv.conf

  echo "===== Wi-Fi status ====="
  wpa_cli -i "$IFACE" -p "$RUN_DIR" status
  echo "===== $IFACE ====="
  ifconfig "$IFACE"
  echo "===== route ====="
  route -n
  echo "===== ping test ====="
  if ping -c 1 -W 2 223.5.5.5 >/dev/null 2>&1; then
    echo "internet=ok"
    return 0
  fi
  if [ -n "$GW" ] && ping -c 1 -W 2 "$GW" >/dev/null 2>&1; then
    echo "gateway=ok"
  else
    echo "gateway=fail"
  fi
  echo "internet=fail"
  return 1
}

while IFS='|' read -r ssid pass; do
  [ -z "$ssid" ] && continue
  if connect_profile "$ssid" "$pass"; then
    exit 0
  fi
done < "$TMP_ORDERED"

echo "All Wi-Fi profiles failed"
exit 1
