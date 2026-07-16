#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_ID="${CLOUDBASE_ENV_ID:-cloud1-d6gv6t2jf3f2c541c}"
ENDPOINT="${CLOUD_SYNC_ENDPOINT:-https://cloud1-d6gv6t2jf3f2c541c-1441069580.ap-shanghai.app.tcloudbase.com/api}"

if [ -n "${CLOUDBASE_CLI:-}" ]; then
  CLI="$CLOUDBASE_CLI"
elif command -v tcb >/dev/null 2>&1; then
  CLI="$(command -v tcb)"
elif command -v cloudbase >/dev/null 2>&1; then
  CLI="$(command -v cloudbase)"
else
  printf '[cloudbase] 未找到 CloudBase CLI。请先安装并执行 tcb login。\n' >&2
  exit 1
fi

PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"
[ -n "$PYTHON" ] || {
  printf '[cloudbase] 未找到 Python 3。\n' >&2
  exit 1
}

exec "$PYTHON" "$ROOT_DIR/scripts/deploy_cloudbase_sync.py" \
  --cli "$CLI" \
  --env-id "$ENV_ID" \
  --endpoint "$ENDPOINT" \
  --function-dir "$ROOT_DIR/cloudbase/cloudfunctions/api"
