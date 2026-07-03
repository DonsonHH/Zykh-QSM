# QSM Integration

## Overview

The local master application talks to QSM368ZP-WF through one gateway adapter:

```text
React/Vite UI -> FastAPI -> services/qsm_client.py -> http://127.0.0.1:18080
```

QSM owns peripheral collection and execution control. The local app owns UI, workflow, local records, risk prompts, candidate medicine matching, and dry-run confirmation.

## Modes

The default mode is:

```text
QSM_MODE=mock
QSM_BASE_URL=http://127.0.0.1:18080
QSM_TIMEOUT_SECONDS=2
DISPENSE_DRY_RUN=true
```

`QSM_MODE=mock` returns stable demo data without requiring the external gateway.

`QSM_MODE=real` calls the gateway base URL. If the gateway is not reachable, the backend returns `connected=false` and a readable `error_message`; the dashboard continues to render and shows the device as temporarily unavailable.

## Port forwarding

Use the helper script:

```bash
cd zykh_station_app
sh scripts/adb_forward.sh
```

The script checks the local command, checks for a connected device, and attempts:

```bash
adb forward tcp:18080 tcp:8080
```

If any step fails, it prints a clear warning and exits without breaking the app; continue with `QSM_MODE=mock`.

## Supported adapter methods

- `health_check()`
- `get_qsm_status()`
- `read_vitals()`
- `get_device_status()`
- `capture_camera()`
- `dispense(slot, dry_run=True)`

Camera capture is a reserved seam in this stage. It may return a structured unavailable response when the gateway does not expose an image endpoint.

`dispense(..., dry_run=True)` never triggers physical dispense. With `DISPENSE_DRY_RUN=true`, 取药确认 only writes local records and returns the dry-run message.

## Verification

Mock mode:

```bash
QSM_MODE=mock sh scripts/start_backend.sh
curl http://127.0.0.1:8000/api/qsm/status
```

Real mode without gateway:

```bash
QSM_MODE=real QSM_BASE_URL=http://127.0.0.1:18080 sh scripts/start_backend.sh
curl http://127.0.0.1:8000/api/qsm/status
```

Expected behavior: HTTP 200, `connected=false`, and `error_message` set.
