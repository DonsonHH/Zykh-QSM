#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
APP_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
SERVICE_DIR="${HOME}/.config/systemd/user"
SERVICE_FILE="${SERVICE_DIR}/zykh-qsm.service"
OLD_SERVICE_NAME="zykh-jetson.service"

mkdir -p "${SERVICE_DIR}"
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Zykh QSM Master Backend
After=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_ROOT}
ExecStart=${SCRIPT_DIR}/start_qsm_app.sh
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
if systemctl --user list-unit-files "${OLD_SERVICE_NAME}" >/dev/null 2>&1; then
  systemctl --user disable --now "${OLD_SERVICE_NAME}" >/dev/null 2>&1 || true
  echo "Disabled old ${OLD_SERVICE_NAME}"
fi
systemctl --user enable zykh-qsm.service
echo "Installed ${SERVICE_FILE}"
echo "Start with: systemctl --user start zykh-qsm.service"
