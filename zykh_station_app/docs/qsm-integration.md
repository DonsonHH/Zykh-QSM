# QSM Integration

## Overview

The local master application talks to QSM368ZP-WF through one gateway adapter for peripheral functions:

```text
React/Vite UI -> FastAPI -> services/qsm_client.py -> http://127.0.0.1:18080
                                   qsm_face_client.py -> http://127.0.0.1:18081
                                   routers/audio.py -> http://127.0.0.1:18082
                                   local_ai_client.py -> http://127.0.0.1:18083
                                   qsm_fingerprint_client.py -> http://127.0.0.1:18086
```

QSM owns camera capture/streaming, face feature matching, temperature, integrated UART vitals, audio, cabinet-control peripherals and the llama.cpp offline language-model process. The local app owns UI, workflow, local records, safety rules, candidate medicine matching and 取药确认.

Latest hardware split:

```text
Host app: React/Vite, FastAPI, SQLite, inquiry workflow, barcode/medicine recognition, identity mapping, touch UI.
Peripheral gateway: FF Camera, face runtime, AS608 fingerprint templates, GY-614 forehead temperature, UART8 integrated vitals, audio, cabinet control.
```

QSM exposes MJPEG and still-capture endpoints on its main gateway. FastAPI proxies `/api/camera/stream`, saves recent real frames for barcode recognition and retries the brief 5xx window caused by switching between live preview and face matching.

## Modes

The default mode is:

```text
QSM_MODE=real
QSM_BASE_URL=http://127.0.0.1:18080
QSM_TIMEOUT_SECONDS=5
QSM_FACE_BASE_URL=http://127.0.0.1:18081
QSM_FACE_TIMEOUT_SECONDS=25
QSM_MIC_BASE_URL=http://127.0.0.1:18082
QSM_MIC_STATUS_PATH=/api/audio/capture/status
QSM_MIC_STREAM_PATH=/api/audio/capture/stream
QSM_MIC_RECORD_PATH=/api/audio/capture/record
QSM_MIC_VOLUME_PATH=/api/audio/capture/volume
QSM_FINGERPRINT_BASE_URL=http://127.0.0.1:18086
QSM_FINGERPRINT_TEMPLATE_START=16
QSM_VITALS_PREFER_FULL=false
QSM_STATUS_PATH=/api/status
QSM_VITALS_ALL_PATH=/api/vitals/read_all
QSM_VITALS_PATH=/api/vitals/read
QSM_TEMP_PATH=/api/vitals/temp/read
QSM_DISPENSE_PATH=/api/dispense
QSM_AUDIO_ASR_PATH=/api/audio/asr
QSM_AUDIO_STATUS_PATH=/api/audio/status
QSM_AUDIO_SPEAK_PATH=/api/audio/speak
QSM_AUDIO_BEEP_PATH=/api/audio/beep
QSM_AUDIO_TIMEOUT_SECONDS=120
LOCAL_CAMERA_MODE=real
LOCAL_CAMERA_DEVICE=auto
DISPENSE_DRY_RUN=false
ENABLE_REAL_DISPENSE=1
LOCAL_AI_BASE_URL=http://127.0.0.1:18083
LOCAL_AI_MODEL=Qwen3.5-0.8B-Q4_K_M
```

`QSM_MODE=real` calls the gateway base URL. If the gateway is not reachable, the backend returns `connected=false` and a readable `error_message`; the dashboard continues to render and shows the device as temporarily unavailable. It does not silently replace failed real calls with fake vitals, fake scan results or fake dispense success.

`QSM_MODE=mock` is still available for isolated local checks, but it is no longer the default.

The path settings are reserved for gateway deployments that expose different HTTP paths. Stage six uses:

- `QSM_STATUS_PATH` for external gateway status.
- `QSM_TEMP_PATH` for the default quick temperature read.
- `QSM_VITALS_ALL_PATH` and `QSM_VITALS_PATH` for full vitals checks when `QSM_VITALS_PREFER_FULL=true`.
- `QSM_DISPENSE_PATH` for取药确认 physical gateway action.
- `QSM_AUDIO_ASR_PATH`, `QSM_AUDIO_STATUS_PATH`, `QSM_AUDIO_SPEAK_PATH` and `QSM_AUDIO_BEEP_PATH` for audio.
- `QSM_CAMERA_CAPTURE_PATH` and `QSM_CAMERA_STREAM_PATH` for QSM camera frames.
- `QSM_FACE_*_PATH` for QSM-side identity status, matching, enrollment and listing.

`LOCAL_CAMERA_*` remains as a legacy configuration seam, but the active terminal workflow uses the QSM camera and does not silently fall back to host-camera mock data.

## Port forwarding

Use the helper script:

```bash
cd zykh_station_app
sh scripts/adb_forward.sh
```

The script checks the local command, checks for a connected device, and attempts:

```bash
adb forward tcp:18080 tcp:8080
adb forward tcp:18081 tcp:8081
adb forward tcp:18082 tcp:8082
adb forward tcp:18083 tcp:8083
adb forward tcp:18086 tcp:8086
```

If any step fails, it prints a clear warning and exits without killing the app. Fix the gateway connection before real-device verification.

## UART8 integrated vitals sensor

The current heart-rate/blood-oxygen module is connected to QSM UART8 and uses a 24-byte binary protocol:

```text
device: /dev/ttyS8
serial: 9600, 8N1, no flow control
start:  0x24
stop:   0x2A
frame:  FF 01 ... F1 (24 bytes)
```

The medicine cabinet remains on `/dev/ttyS5`. Deploy the reader and restart wrapper with:

```bash
cd zykh_station_app
sh scripts/deploy_qsm_gateway.sh
```

The deployed reader buffers arbitrary UART chunks, resynchronizes on `0xFF`, validates the `FF 01` header and `0xF1` trailer, and waits for stable measurement frames. A non-blocking process lock prevents concurrent HTTP requests from interleaving UART start/stop bytes. Non-zero readings are preserved even when they fall outside common reference ranges; risk interpretation belongs to the safety layer, not the transport parser. It writes the legacy `heart_rate_bpm` and `spo2_percent` keys expected by the existing Perl gateway plus these optional fields:

- `systolic_pressure` and `diastolic_pressure`;
- `respiratory_rate`;
- `microcirculation`, `fatigue`, `rr_interval`;
- `hrv_sdnn` and `hrv_rmssd`;
- raw body/ambient temperature integer and decimal bytes.

`VITALS_UART_TEMP_DECIMAL_SCALE` defaults to `100`, so bytes `36,11` are exposed as a `36.11°C` fingertip-temperature reference. The separate GY-614 remains the authoritative forehead-temperature source. Heart rate and SpO2 are treated as core measurements; blood pressure and HRV are displayed only as auxiliary reference data when the module actually emits non-zero values.

The UART collection window defaults to 16 seconds. This stays below the existing QSM gateway's 18-second sensor-process limit while providing 60% more collection time than the previous 10-second window. The reader waits for at least three heart-rate/SpO2 frames and, when available, two blood-pressure and HRV frames. Each field independently uses the median of its five most recent non-zero samples, so sparse reference values are not discarded merely because they occur in different frames. Fewer than three core frames are reported as `poor_signal`; blood-pressure and HRV values are never synthesized when the module does not emit them. The host allows up to 30 seconds for the combined UART8 and GY-614 response, while the terminal presents an 18-second guided measurement window. A busy UART returns a structured error instead of starting a second overlapping measurement.

## Supported adapter methods

- `health_check()`
- `get_qsm_status()`
- `read_vitals()`
- `read_full_vitals()`
- `read_temperature()`
- `get_device_status()`
- `dispense(slot, dry_run=False)`
- `audio_asr()`
- `audio_status()`
- `audio_speak()`
- `audio_beep()`

QSM camera proxy methods live in `services/qsm_camera_service.py`. Normal identity calls use `services/qsm_face_client.py`; `services/identity_service.py` only resolves identities already bound to service users. Unknown or historical unbound face subjects are reported during wake-time recognition. The separate dispense verification endpoint can create a clearly labelled local visitor only after the user explicitly selects face confirmation.

Fingerprint calls use `services/qsm_fingerprint_client.py`. The AS608 module stores fingerprint templates; SQLite stores only `template_id -> service_user_id`, last-seen time and match score. Existing board templates are never treated as identities unless they have a local binding. IDs 0-15 are reserved by default so the verified pre-existing board template is not overwritten.

The FF Camera microphone is captured on QSM by the dedicated port `8082` gateway. It auto-detects the ALSA `FF Camera`/`Camera` card and exposes real `S16_LE`, 16 kHz, mono PCM. The host realtime-ASR websocket consumes that stream directly, so browser microphone permissions and a host microphone are not required. Online mode sends it to Qwen realtime ASR; local mode converts it to float PCM and sends it to the QSM sherpa-onnx server on board port `8084` (host forward `18084`). Capture gain changes are forwarded to the QSM `Mic` mixer control.

The speaker has two low-latency paths. Online Qwen realtime TTS writes 24 kHz PCM deltas to board port `19001` as they arrive. Offline TTS uses the resident VITS service on board loopback port `19002`, which avoids reloading the model and plays callback chunks during synthesis. Both paths return structured latency metrics and fall back without exposing transport details in the terminal UI.

WiFi strength comes from the host `iw ... link` dBm value. SIM strength comes from the QSM EC200A `AT+CSQ` response and is converted to dBm, percentage and 0-4 bars. The top bar therefore reflects each live link independently instead of assuming full signal.

By default the app uses the real cabinet-control path: `DISPENSE_DRY_RUN=false` and `ENABLE_REAL_DISPENSE=1`. The user explicitly starts fingerprint or face confirmation in the 取药确认 modal. A successful result is shown with the resolved local user before the UI sends `confirm_real_dispense=true`, writes the local record and calls the gateway dispense path. `REAL_DISPENSE_TEST_SLOT` is optional and can limit physical tests to one safe slot. For non-physical checks, use `POST /api/qsm/dispense/dry-run` or temporarily set `DISPENSE_DRY_RUN=true`.

`scripts/deploy_qsm_gateway.sh` can install the AS608 payload when it finds `QSM368ZP-AS608-offline-deploy(1).zip` at the repository root, or when `QSM_FINGERPRINT_BUNDLE` points to the package. Template IDs `0..15` remain reserved; host-created bindings start at 16. Fingerprint templates stay inside AS608 and face features stay on QSM. The host stores only local subject mappings, match counters, last-seen timestamps and dispense audit records.

## Device endpoints

```text
POST /api/vitals/read-all
POST /api/camera/capture
GET  /api/camera/stream
POST /api/medicine/scan
POST /api/audio/asr
GET  /api/audio/status
POST /api/audio/speak
POST /api/audio/beep
POST /api/qsm/dispense/dry-run
GET  /api/qsm/capabilities
GET  /api/identity/status
POST /api/identity/resolve
POST /api/identity/enroll/{service_user_id}
GET  /api/fingerprint/status
POST /api/fingerprint/identify
POST /api/fingerprint/enroll/{service_user_id}
DELETE /api/fingerprint/{service_user_id}
```

Real mode without gateway:

- status and vitals return HTTP 200 with unavailable state.
- camera and identity endpoints return structured unavailable states when their QSM gateway is unreachable.
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

Successful integrated-vitals responses preserve `heart_rate`, `spo2`, `systolic_pressure`, `diastolic_pressure`, `respiratory_rate`, `hrv_sdnn`, `hrv_rmssd`, and `sensor_model`. Zero placeholders from the sensor are normalized to `null` rather than shown as real readings.

Real dispense smoke is intentionally omitted from the generic checklist. Only run it after configuring a safe slot and confirming the device is ready.

## AI And Recognition

Medicine scan follows this order:

- reuse the latest real QSM stream frame, or request one QSM still frame;
- decode a local barcode if a decoder is installed or configured;
- call Qwen visual recognition if `DASHSCOPE_API_KEY` or `DASHSCOPE_API_KEY_FILE` is configured;
- return `manual_required` if recognition still fails.

Inquiry AI follows this order:

- call the configured DeepSeek-compatible cloud endpoint from the host when `AI_API_KEY` or `AI_API_KEY_FILE` is available;
- when the key is missing, connectivity fails or the cloud request errors, call Qwen3.5 through QSM llama.cpp on port `8083`;
- if the offline model is also unavailable or returns invalid output, continue with deterministic safety rules and mark `source=rules_fallback`.

The offline model is a real board-side process, not mock data. See [`offline-ai.md`](offline-ai.md) for model hashes, download/deploy commands, measured resource use and disconnected validation.

## QSM face identity

`scripts/deploy_qsm_gateway.sh` starts the main gateway on board port `8080`, the face gateway on `8081`, and the FF Camera microphone gateway on `8082`. The face runtime reads `/dev/video23`, performs feature extraction/matching on QSM and stores its template database under `/userdata/qsm-face/data`. The host stores only the opaque face subject to service-user mapping.

Matched users are attached to inquiry and dispense records. Identity resolution uses multiple-frame voting instead of accepting one highest-scoring frame. Normal wake-time recognition never creates a person automatically. In the dispense modal, the user can explicitly choose face confirmation; if no existing subject matches, the app creates a clearly labelled local visitor and enrolls that face so later取药 records can identify the same person. Administrators can rename or complete that visitor in Settings. After terminal inactivity, the wake screen clears the previous identity; tapping the screen starts a fresh recognition before personal tasks are loaded.

The bundled InspireFace community model is licensed for academic use only. A commercial deployment must replace it with a model and runtime carrying the required commercial rights.

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
