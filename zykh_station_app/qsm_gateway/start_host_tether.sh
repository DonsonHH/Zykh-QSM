#!/bin/sh
set -u

HOST_INTERFACE="${QSM_HOST_INTERFACE:-usb1}"
WAN_INTERFACE="${QSM_WAN_INTERFACE:-usb0}"
HOST_ADDRESS="${QSM_HOST_GATEWAY_ADDRESS:-192.168.77.1}"
HOST_CIDR="${QSM_HOST_CIDR:-24}"

log() {
  printf '[qsm-tether] %s\n' "$*"
}

fail() {
  printf '[qsm-tether] FAIL: %s\n' "$*" >&2
  exit 1
}

[ "${1:-start}" = "start" ] || fail "仅支持 start"
command -v ifconfig >/dev/null 2>&1 || fail "缺少 ifconfig"
command -v iptables >/dev/null 2>&1 || fail "缺少 iptables"
[ -d "/sys/class/net/$HOST_INTERFACE" ] || fail "未找到主机连接接口 $HOST_INTERFACE"
[ -d "/sys/class/net/$WAN_INTERFACE" ] || fail "未找到数据网络接口 $WAN_INTERFACE"

ifconfig "$HOST_INTERFACE" "$HOST_ADDRESS" netmask 255.255.255.0 up \
  || fail "无法配置 $HOST_INTERFACE"
printf '1\n' > /proc/sys/net/ipv4/ip_forward \
  || fail "无法启用 IPv4 转发"

iptables -t nat -C POSTROUTING -o "$WAN_INTERFACE" -j MASQUERADE 2>/dev/null \
  || iptables -t nat -A POSTROUTING -o "$WAN_INTERFACE" -j MASQUERADE \
  || fail "无法配置 NAT"
iptables -C FORWARD -i "$HOST_INTERFACE" -o "$WAN_INTERFACE" -j ACCEPT 2>/dev/null \
  || iptables -A FORWARD -i "$HOST_INTERFACE" -o "$WAN_INTERFACE" -j ACCEPT \
  || fail "无法配置上行转发"
iptables -C FORWARD -i "$WAN_INTERFACE" -o "$HOST_INTERFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
  || iptables -A FORWARD -i "$WAN_INTERFACE" -o "$HOST_INTERFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT \
  || fail "无法配置回程转发"

log "$HOST_INTERFACE=$HOST_ADDRESS/$HOST_CIDR -> $WAN_INTERFACE"
log "QSM_TETHER_READY"
