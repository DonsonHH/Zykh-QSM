#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SOURCE="$SCRIPT_DIR/zykh-qsm-tether"
TARGET="/usr/local/sbin/zykh-qsm-tether"
SUDOERS="/etc/sudoers.d/zykh-qsm-tether"
TARGET_USER="${SUDO_USER:-${USER:-jetson}}"

[ "$(id -u)" -eq 0 ] || {
  echo "该安装步骤需要一次管理员授权。" >&2
  exec sudo "$0"
}
[ -f "$SOURCE" ] || { echo "找不到 $SOURCE" >&2; exit 1; }

install -o root -g root -m 0755 "$SOURCE" "$TARGET"
printf '%s ALL=(root) NOPASSWD: %s *\n' "$TARGET_USER" "$TARGET" > "$SUDOERS"
chmod 0440 "$SUDOERS"

if command -v visudo >/dev/null 2>&1; then
  visudo -cf "$SUDOERS" >/dev/null || {
    rm -f "$SUDOERS"
    echo "sudoers 校验失败，已撤销规则。" >&2
    exit 1
  }
fi

echo "QSM 主机数据网络助手已安装。"
