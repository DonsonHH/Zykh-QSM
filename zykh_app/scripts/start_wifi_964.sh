#!/bin/sh

set -u

SSID="${WIFI_SSID:-LAPTOP-BSM79J69 1593}"
PASSWORD="${WIFI_PASSWORD:-}"
CONF=/userdata/wpa_laptop_bsm79j69.conf
RUN_DIR=/var/run/wpa_supplicant

if [ -z "$PASSWORD" ] && [ -s /userdata/wifi_password.txt ]; then
  PASSWORD=$(cat /userdata/wifi_password.txt)
fi

if [ -z "$PASSWORD" ]; then
  echo "Missing Wi-Fi password. Set WIFI_PASSWORD or write /userdata/wifi_password.txt"
  exit 1
fi

echo "===== Restart Wi-Fi: $SSID ====="

killall dhcpcd 2>/dev/null || true
killall udhcpc 2>/dev/null || true
killall wpa_supplicant 2>/dev/null || true

mkdir -p "$RUN_DIR"

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
    IFACE="$dev"
    break
  fi
done

if [ -z "$IFACE" ]; then
  echo "No wlan interface found"
  exit 1
fi

echo "interface=$IFACE"
ifconfig "$IFACE" up
rm -f "$RUN_DIR/$IFACE" 2>/dev/null || true
wpa_supplicant -B -i "$IFACE" -c "$CONF" -C "$RUN_DIR"

echo "===== Wait for Wi-Fi connection ====="
i=0
while [ "$i" -lt 25 ]; do
  state=$(wpa_cli -i "$IFACE" -p "$RUN_DIR" status 2>/dev/null | grep '^wpa_state=' | cut -d= -f2)
  echo "wpa_state=$state"
  [ "$state" = "COMPLETED" ] && break
  wpa_cli -i "$IFACE" -p "$RUN_DIR" reconnect >/dev/null 2>&1 || true
  sleep 2
  i=$((i + 1))
done

echo "===== Request DHCP ====="
udhcpc -i "$IFACE" -n -q

echo "===== Fix route and DNS ====="
route del default dev usb1 2>/dev/null || true
route del default dev usb0 2>/dev/null || true
printf 'nameserver 223.5.5.5\nnameserver 114.114.114.114\nnameserver 8.8.8.8\n' > /tmp/resolv.conf

echo "===== Sync Beijing time ====="
export TZ=CST-8
echo "Skip rdate auto-sync to avoid timezone drift; sync from host with adb date -s when needed."
date

echo "===== Wi-Fi status ====="
wpa_cli -i "$IFACE" -p "$RUN_DIR" status

echo "===== $IFACE ====="
ifconfig "$IFACE"

echo "===== route ====="
route -n

echo "===== resolv.conf ====="
cat /etc/resolv.conf 2>/dev/null || cat /tmp/resolv.conf
