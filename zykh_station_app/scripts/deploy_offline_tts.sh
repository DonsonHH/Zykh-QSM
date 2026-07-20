#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
printf '[host-offline-tts] 离线 TTS 不再部署到 QSM，改为部署到主机。\n'
exec sh "$SCRIPT_DIR/deploy_host_offline_tts.sh" "$@"
