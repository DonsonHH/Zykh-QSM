#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_ID="${CLOUDBASE_ENV_ID:-cloud1-d6gv6t2jf3f2c541c}"
FUNCTION_DIR="$ROOT_DIR/cloudbase/cloudfunctions/api"

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

[ -f "$FUNCTION_DIR/index.js" ] || {
  printf '[cloudbase] 找不到云函数源码：%s\n' "$FUNCTION_DIR" >&2
  exit 1
}

printf '[cloudbase] 环境：%s\n' "$ENV_ID"
printf '[cloudbase] 请先在云开发控制台确认集合存在：service_users、today_plans、inquiries。\n'
"$CLI" -e "$ENV_ID" fn deploy api --force --dir "$FUNCTION_DIR" --httpFn --path /api
printf '[cloudbase] api 云函数部署完成。\n'
