# QSM Integration

## Overview

The local master application talks to QSM368ZP-WF through one gateway adapter for peripheral functions:

```text
React/Vite UI -> FastAPI -> services/qsm_client.py -> http://127.0.0.1:18080
```

QSM owns temperature, heart rate/blood oxygen, audio and cabinet-control peripherals. The local app owns UI, workflow, local records, risk prompts, candidate medicine matching,取药确认 and host-side camera capture.

Latest hardware split:

```text
Host app: React/Vite, FastAPI, SQLite, inquiry workflow, camera recognition, touch UI.
Peripheral gateway: temperature, heart rate/blood oxygen, audio, cabinet control.
```

Camera capture no longer depends on the peripheral gateway. The business endpoint `/api/qsm/camera/capture` is kept as a stable app-facing action, but internally it calls the host-side camera seam.

## Modes

The default mode is:

```text
QSM_MODE=real
QSM_BASE_URL=http://127.0.0.1:18080
QSM_TIMEOUT_SECONDS=2
QSM_VITALS_PREFER_FULL=false
QSM_STATUS_PATH=/api/status
QSM_VITALS_ALL_PATH=/api/vitals/read_all
QSM_VITALS_PATH=/api/vitals/read
QSM_TEMP_PATH=/api/vitals/temp/read
QSM_DISPENSE_PATH=/api/dispense
QSM_AUDIO_ASR_PATH=/api/audio/asr
QSM_AUDIO_SPEAK_PATH=/api/audio/speak
QSM_AUDIO_BEEP_PATH=/api/audio/beep
LOCAL_CAMERA_MODE=real
LOCAL_CAMERA_DEVICE=auto
DISPENSE_DRY_RUN=true
ENABLE_REAL_DISPENSE=0
```

`QSM_MODE=real` calls the gateway base URL. If the gateway is not reachable, the backend returns `connected=false` and a readable `error_message`; the dashboard continues to render and shows the device as temporarily unavailable. It does not silently replace failed real calls with fake vitals, fake scan results or fake dispense success.

`QSM_MODE=mock` is still available for isolated local checks, but it is no longer the default.

The path settings are reserved for gateway deployments that expose different HTTP paths. Stage six uses:

- `QSM_STATUS_PATH` for external gateway status.
- `QSM_TEMP_PATH` for the default quick temperature read.
- `QSM_VITALS_ALL_PATH` and `QSM_VITALS_PATH` for full vitals checks when `QSM_VITALS_PREFER_FULL=true`.
- `QSM_DISPENSE_PATH` for取药确认 physical gateway action.
- `QSM_AUDIO_ASR_PATH`, `QSM_AUDIO_SPEAK_PATH` and `QSM_AUDIO_BEEP_PATH` for audio.

`LOCAL_CAMERA_MODE=real` checks the configured host camera device. `LOCAL_CAMERA_DEVICE=auto` probes common FF Camera nodes and `/dev/video*`; a direct path such as `/dev/video2` is also supported. `LOCAL_CAMERA_MODE=mock` only exists for isolated local checks.

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

If any step fails, it prints a clear warning and exits without killing the app. Fix the gateway connection before real-device verification.

## Supported adapter methods

- `health_check()`
- `get_qsm_status()`
- `read_vitals()`
- `read_temperature()`
- `get_device_status()`
- `dispense(slot, dry_run=False)`
- `audio_asr()`
- `audio_speak()`
- `audio_beep()`

Host camera methods live in `services/local_camera.py`. In real mode, the service captures one image from the configured local camera and returns a structured unavailable response if the device or capture command fails.

By default `DISPENSE_DRY_RUN=true`, so 取药确认 writes a local dry-run record and never calls the gateway dispense path. Real dispense requires all safety gates: `DISPENSE_DRY_RUN=false`, `ENABLE_REAL_DISPENSE=1`, `REAL_DISPENSE_TEST_SLOT` configured, and request body `confirm_real_dispense=true`.

## Device endpoints

```text
POST /api/vitals/read-all
POST /api/camera/capture
POST /api/medicine/scan
POST /api/audio/asr
POST /api/audio/speak
POST /api/audio/beep
POST /api/qsm/dispense/dry-run
GET  /api/qsm/capabilities
```

Real mode without gateway:

- status and vitals return HTTP 200 with unavailable state.
- camera capture still follows host-side camera availability.
- audio and dispense actions return structured gateway errors.
- capabilities returns `qsm_connected=false` when the gateway is unreachable.

## Verification

Real mode:

```bash
QSM_MODE=real QSM_BASE_URL=http://127.0.0.1:18080 sh scripts/start_backend.sh
curl http://127.0.0.1:8000/api/qsm/status
curl -X POST http://127.0.0.1:8000/api/vitals/read-all
curl -X POST http://127.0.0.1:8000/api/audio/beep
```

Gateway unavailable expected behavior: HTTP 200, `connected=false` or `ok=false`, and `error_message` set.

Real dispense smoke is intentionally omitted from the generic checklist. Only run it after configuring a safe slot and confirming the device is ready.

## AI And Recognition

Medicine scan follows this order:

- capture a real host-camera image;
- decode a local barcode if a decoder is installed or configured;
- call Qwen visual recognition if `DASHSCOPE_API_KEY` or `DASHSCOPE_API_KEY_FILE` is configured;
- return `manual_required` if recognition still fails.

Inquiry AI follows this order:

- call the configured DeepSeek-compatible cloud endpoint when `AI_API_KEY` or `AI_API_KEY_FILE` is available;
- return a marked `local_fallback` rules response when offline or unconfigured.

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

It returns HTTP 200 in real mode without a gateway and real mode with a gateway. When real mode is unavailable, the response includes warnings and recommendations instead of raising a server error.
