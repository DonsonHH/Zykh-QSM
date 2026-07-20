#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
printf '[host-offline-tts] QSM 端常驻 TTS 已停用，改为部署主机离线 TTS。\n'
exec sh "$SCRIPT_DIR/deploy_host_offline_tts.sh" "$@"
