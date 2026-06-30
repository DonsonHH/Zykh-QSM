#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
APP_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
SERVICE_DIR="${HOME}/.config/systemd/user"
SERVICE_FILE="${SERVICE_DIR}/zykh-jetson.service"

mkdir -p "${SERVICE_DIR}"
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Zykh Jetson Master Backend
After=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_ROOT}
ExecStart=${SCRIPT_DIR}/start_jetson_app.sh
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable zykh-jetson.service
echo "Installed ${SERVICE_FILE}"
echo "Start with: systemctl --user start zykh-jetson.service"
