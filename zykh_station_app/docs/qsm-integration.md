# QSM Integration

## Overview

The local master application talks to QSM368ZP-WF through one gateway adapter for peripheral functions:

```text
React/Vite UI -> FastAPI -> services/qsm_client.py -> http://127.0.0.1:18080
```

QSM owns temperature, heart rate/blood oxygen, audio and cabinet-control peripherals. The local app owns UI, workflow, local records, risk prompts, candidate medicine matching, dry-run confirmation and host-side camera capture.

Latest hardware split:

```text
Host app: React/Vite, FastAPI, SQLite, inquiry workflow, camera recognition, touch UI.
Peripheral gateway: temperature, heart rate/blood oxygen, audio, cabinet control.
```

Camera capture no longer depends on the peripheral gateway. The business endpoint `/api/qsm/camera/capture` is kept as a stable app-facing action, but internally it calls the host-side camera seam.

## Modes

The default mode is:

```text
QSM_MODE=mock
QSM_BASE_URL=http://127.0.0.1:18080
QSM_TIMEOUT_SECONDS=2
QSM_STATUS_PATH=/api/status
QSM_VITALS_PATH=/api/vitals/read
QSM_CAMERA_CAPTURE_PATH=/api/camera/capture
QSM_DISPENSE_PATH=/api/dispense
LOCAL_CAMERA_MODE=mock
LOCAL_CAMERA_DEVICE=0
DISPENSE_DRY_RUN=true
```

`QSM_MODE=mock` returns stable demo data without requiring the external gateway.

`QSM_MODE=real` calls the gateway base URL. If the gateway is not reachable, the backend returns `connected=false` and a readable `error_message`; the dashboard continues to render and shows the device as temporarily unavailable.

The path settings are reserved for gateway deployments that expose different HTTP paths. Stage six uses:

- `QSM_STATUS_PATH` for external gateway status.
- `QSM_VITALS_PATH` for external gateway vitals.
- `QSM_DISPENSE_PATH` as the reserved physical dispense path.
- `QSM_CAMERA_CAPTURE_PATH` only as a reserved legacy path; current camera capture is host-side.

`LOCAL_CAMERA_MODE=mock` returns a stable recognition sample. `LOCAL_CAMERA_MODE=real` checks the configured host camera device. On Linux, `LOCAL_CAMERA_DEVICE=0` maps to `/dev/video0`; a direct path such as `/dev/video2` is also supported.

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
- `dispense(slot, dry_run=True)`

Host camera methods live in `services/local_camera.py`. In mock mode, camera capture returns a stable medicine-recognition sample. In real mode, the service checks the configured local camera device and returns a structured unavailable response if the device is missing.

`dispense(..., dry_run=True)` never triggers physical dispense. With `DISPENSE_DRY_RUN=true`, 取药确认 only writes local records and returns the dry-run message.

## Stage six endpoints

```text
GET  /api/qsm/vitals
POST /api/qsm/camera/capture
POST /api/qsm/dispense/dry-run
GET  /api/qsm/capabilities
```

Mock mode:

- vitals returns temperature `35.7`, with heart rate and blood oxygen unavailable.
- camera capture returns the sample medicine recognition result.
- dispense dry-run writes a local dry-run record.
- capabilities returns mock/dry-run states.

Real mode without gateway:

- status and vitals return HTTP 200 with unavailable state.
- camera capture still follows host-side camera availability.
- dry-run remains local and does not open a cabinet.
- capabilities returns `qsm_connected=false` when the gateway is unreachable.

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

Stage six still does not perform physical dispense. Keep `DISPENSE_DRY_RUN=true` for all demonstrations.

## Stage seven check workflow

Use the scripted check before real-device demonstrations:

```bash
cd zykh_station_app
sh scripts/adb_forward.sh
sh scripts/check_devices.sh
```

`check_devices.sh` reports `OK`, `WARN` and `FAIL` lines and does not stop the project when a peripheral is missing.

The backend also exposes:

```text
GET /api/device/check
```

It returns HTTP 200 in mock mode, real mode without a gateway, and real mode with a gateway. When real mode is unavailable, the response includes warnings and recommendations instead of raising a server error.
