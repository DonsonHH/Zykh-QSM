#!/bin/sh
set -u

USB_IFACE="${QSM_4G_IFACE:-usb0}"
DNS_FILE="${QSM_DNS_FILE:-/tmp/resolv.conf}"
PING_IP="${QSM_PING_IP:-223.5.5.5}"
PING_HOST="${QSM_PING_HOST:-www.baidu.com}"
HTTP_TEST_URL="${QSM_HTTP_TEST_URL:-http://www.baidu.com}"

ok() {
  printf 'OK   %s\n' "$1"
}

warn() {
  printf 'WARN %s\n' "$1"
}

run_step() {
  label="$1"
  shift
  printf '[*] %s\n' "$label"
  if "$@"; then
    ok "$label"
    return 0
  fi
  warn "$label"
  return 1
}

echo "===== Start QSM 4G Network ====="

if command -v lsusb >/dev/null 2>&1; then
  if lsusb | grep -qi '2c7c:6005'; then
    ok "EC200A / Quectel USB module detected."
  else
    warn "EC200A USB id 2c7c:6005 not found. Check module, SIM, antenna and power."
  fi
else
  warn "lsusb not found; skip USB id check."
fi

echo "===== Modem ports ====="
ls -l /dev/ttyUSB* 2>/dev/null || warn "No /dev/ttyUSB* device found."

echo "===== Kernel hints ====="
dmesg 2>/dev/null | grep -i -E 'usb|ttyUSB|option|cdc|ether|quectel|ec200' | tail -40 || true

echo "===== Stop Wi-Fi ====="
killall wpa_supplicant 2>/dev/null || true
ifconfig wlan0 down 2>/dev/null || true

run_step "Bring up ${USB_IFACE}" ifconfig "$USB_IFACE" up
run_step "Refresh IP from EC200A" udhcpc -i "$USB_IFACE" -n -q

echo "===== Remove wrong default routes ====="
route del default dev wlan0 2>/dev/null || true
route del default dev usb1 2>/dev/null || true

if ! route -n 2>/dev/null | awk -v iface="$USB_IFACE" '$1 == "0.0.0.0" && $8 == iface { found=1 } END { exit(found ? 0 : 1) }'; then
  warn "Default route is not on ${USB_IFACE}; refreshing DHCP once."
  udhcpc -i "$USB_IFACE" -n -q 2>/dev/null || true
fi

echo "===== DNS ====="
printf 'nameserver 223.5.5.5\nnameserver 114.114.114.114\nnameserver 8.8.8.8\n' > "$DNS_FILE"
cat "$DNS_FILE"

echo "===== ${USB_IFACE} ====="
ifconfig "$USB_IFACE" 2>/dev/null || warn "${USB_IFACE} not available."

echo "===== route ====="
route -n 2>/dev/null || warn "route command failed."

echo "===== Test IP ====="
run_step "Ping ${PING_IP}" ping -c 4 "$PING_IP"

echo "===== Test DNS ====="
run_step "Ping ${PING_HOST}" ping -c 4 "$PING_HOST"

echo "===== Test HTTP ====="
if command -v wget >/dev/null 2>&1; then
  if wget -O - "$HTTP_TEST_URL" 2>/dev/null | head | grep -qi '<!DOCTYPE html\|STATUS OK\|html'; then
    ok "HTTP access works."
  else
    warn "HTTP test did not return expected HTML."
  fi
else
  warn "wget not found; skip HTTP test."
fi

echo "===== 4G Ready Check Finished ====="
