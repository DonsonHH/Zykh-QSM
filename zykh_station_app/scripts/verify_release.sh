#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_DIR="$ROOT_DIR/zykh_station_app"
PYTHON="$APP_DIR/backend/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  printf 'missing Python environment: %s\n' "$PYTHON" >&2
  exit 1
fi

export QSM_MODE=mock
export DISPENSE_DRY_RUN=true
export PYTHONDONTWRITEBYTECODE=1

printf 'CHECK compileall\n'
"$PYTHON" -m compileall -q "$APP_DIR/backend/app"

printf 'CHECK backend pytest\n'
(cd "$APP_DIR/backend" && .venv/bin/python -m pytest -q)

printf 'CHECK qsm pytest\n'
(cd "$ROOT_DIR" && "$PYTHON" -m pytest -q zykh_station_app/qsm_gateway/tests)

printf 'CHECK cabinet v2 firmware contract\n'
(cd "$APP_DIR/qsm_gateway/firmware/cabinet_v2_l432kc" && ./test.sh)

printf 'CHECK frontend static contracts\n'
for test_file in "$APP_DIR"/frontend/scripts/test-*.mjs; do
  if grep -Eq 'spawn\(|fetch\(|127\.0\.0\.1|localhost|playwright|puppeteer|chromium' "$test_file"; then
    continue
  fi
  (cd "$APP_DIR/frontend" && node "scripts/${test_file##*/}")
done

printf 'CHECK frontend build\n'
(cd "$APP_DIR/frontend" && npm run build)

printf 'CHECK cloud contracts\n'
node --test "$APP_DIR/cloudbase/cloudfunctions/api/test-security-contract.cjs"
node --test "$APP_DIR/cloudbase/cloudfunctions/caregiverNotificationWorker"/test-*.cjs
node --test "$APP_DIR/cloudbase/miniprogram/test-sync-contract.cjs"

printf 'CHECK shell lifecycle contracts\n'
bash "$APP_DIR/scripts/tests/test_launch_kiosk_cleanup.sh"
bash "$APP_DIR/scripts/tests/test_launch_kiosk_backend_supervision.sh"
bash "$APP_DIR/scripts/tests/test_start_frontend_production.sh"

printf 'CHECK perl syntax\n'
perl -c "$ROOT_DIR/zykh_app/server.pl"
perl -c "$APP_DIR/qsm_gateway/vitals_gateway.pl"
perl -c "$APP_DIR/qsm_gateway/patch_station_gateway.pl"
perl -I "$APP_DIR/qsm_gateway/lib" -MZykh::CabinetLightProtocol -e 1

printf 'CHECK markdown structure\n'
"$PYTHON" - "$ROOT_DIR" <<'PY'
from pathlib import Path
import re
import subprocess
import sys

root = Path(sys.argv[1])
paths = subprocess.check_output(
    [
        "git",
        "-C",
        str(root),
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        "*.md",
    ],
).split(b"\0")
errors = []

for raw_path in filter(None, paths):
    path = root / raw_path.decode()
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8")
    if any(line.rstrip() != line for line in text.splitlines()):
        errors.append(f"{path}: trailing whitespace")
    if text.count("```") % 2:
        errors.append(f"{path}: unmatched fenced code block")
    for match in re.finditer(r"(?<!!)\[[^\]]*\]\(([^)]+)\)", text):
        target = match.group(1).split("#", 1)[0]
        if not target or "://" in target or target.startswith(("mailto:", "tel:")):
            continue
        if not (path.parent / target).resolve().exists():
            line = text[: match.start()].count("\n") + 1
            errors.append(f"{path}:{line}: missing link target {target}")

if errors:
    raise SystemExit("\n".join(errors))
print(f"markdown structure: ok ({len(paths) - 1} files)")
PY

printf 'RELEASE_CHECKS_OK\n'
