# QSM Integration

## Overview

The local master application talks to QSM368ZP-WF through one gateway adapter for peripheral functions:

```text
React/Vite UI -> FastAPI -> services/qsm_client.py -> http://127.0.0.1:18080
                                   qsm_face_client.py -> http://127.0.0.1:18081
                                   routers/audio.py -> http://127.0.0.1:18082
                                   qsm_fingerprint_client.py -> http://127.0.0.1:18086
```

QSM owns camera capture/streaming, face feature matching, temperature, integrated UART vitals, offline ASR/TTS, audio playback and cabinet-control peripherals. The local app owns UI, workflow, cloud-model orchestration, local records, safety rules, candidate medicine matching and 取药确认. The old QSM llama.cpp assets are diagnostic-only and are stopped during normal kiosk startup.

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
QSM_VITALS_RETRY_ATTEMPTS=2
QSM_VITALS_RETRY_DELAY_SECONDS=0.7
QSM_VITALS_PREFER_FULL=false
QSM_VITALS_BASE_URL=http://127.0.0.1:18085
QSM_VITALS_PREPARE_PATH=/api/vitals/prepare
QSM_VITALS_SESSION_START_PATH=/api/vitals/session/start
QSM_VITALS_SESSION_STATUS_PATH=/api/vitals/session/status
QSM_VITALS_SESSION_CANCEL_PATH=/api/vitals/session/cancel
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
```

`QSM_MODE=real` calls the gateway base URL. If the gateway is not reachable, the backend returns `connected=false` and a readable `error_message`; the dashboard continues to render and shows the device as temporarily unavailable. It does not silently replace failed real calls with fake vitals, fake scan results or fake dispense success.

`QSM_MODE=mock` is still available for isolated local checks, but it is no longer the default.

The path settings are reserved for gateway deployments that expose different HTTP paths. Stage six uses:

- `QSM_STATUS_PATH` for external gateway status.
- `QSM_TEMP_PATH` for the default quick temperature read.
- `QSM_VITALS_ALL_PATH` and `QSM_VITALS_PATH` for full vitals checks when `QSM_VITALS_PREFER_FULL=true`.
- `QSM_VITALS_PREPARE_PATH` starts the UART8 sensor algorithm when the measurement page opens. The session start then flushes preheat frames and collects a fresh stable window.
- `QSM_VITALS_RETRY_ATTEMPTS` and `QSM_VITALS_RETRY_DELAY_SECONDS` for one automatic stabilization retry when temperature, heart rate or blood oxygen is incomplete. Concurrent UI requests share the same physical measurement instead of competing for UART.
- `QSM_DISPENSE_PATH` for取药确认 physical gateway action.
- `QSM_AUDIO_ASR_PATH`, `QSM_AUDIO_STATUS_PATH`, `QSM_AUDIO_SPEAK_PATH` and `QSM_AUDIO_BEEP_PATH` for audio.

### 小程序服药提醒播报

云端命令轮询支持 `AUDIO_SPEAK`。小程序无需访问终端局域网接口，只需沿用现有
`CREATE_COMMAND` 下发命令；终端收到后通过 QSM 喇叭播报并回写命令结果：

```json
{
  "type": "AUDIO_SPEAK",
  "payload": {
    "target_user_name": "张三",
    "medicine_name": "藿香正气丸",
    "volume": 230
  }
}
```

未传 `text` 时会生成“张三，该服用藿香正气丸了。”；也可直接传入不超过 240 字的
`text`。云端轮询失败不会阻断终端本地功能，命令执行和确认仍保存在本地命令历史中。
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
adb forward tcp:18084 tcp:6006
adb forward tcp:18085 tcp:8085
adb forward tcp:18086 tcp:8086
```

The normal helper never forwards or probes the retired llama.cpp ports
`18083/8083`. Those ports remain available only through the explicit legacy
diagnostic scripts. Normal readiness checks require the Paraformer ASR port and
`offline_available=true` from the main gateway's read-only
`GET /api/audio/status`; they do not synthesize or play audio.

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
sh scripts/deploy_qsm_vitals.sh
```

The deployed reader buffers arbitrary UART chunks, resynchronizes on `0xFF`, validates the `FF 01` header and `0xF1` trailer, and waits for stable measurement frames. A non-blocking process lock prevents concurrent HTTP requests from interleaving UART start/stop bytes. Non-zero readings are preserved even when they fall outside common reference ranges; risk interpretation belongs to the safety layer, not the transport parser. It writes the legacy `heart_rate_bpm` and `spo2_percent` keys expected by the existing Perl gateway plus these optional fields:

- `systolic_pressure` and `diastolic_pressure`;
- `respiratory_rate`;
- `microcirculation`, `fatigue`, `rr_interval`;
- `hrv_sdnn` and `hrv_rmssd`;
- raw body/ambient temperature integer and decimal bytes.

`VITALS_UART_TEMP_DECIMAL_SCALE` defaults to `100`, so bytes `36,11` are exposed as a `36.11°C` fingertip-temperature reference. The separate GY-614 remains the authoritative forehead-temperature source. Heart rate and SpO2 are treated as core measurements; blood pressure and HRV are displayed only as auxiliary reference data when the module actually emits non-zero values.

The 8085 gateway owns one measurement session at a time. It runs UART8 and GY-614 reads concurrently and retries the UART start sequence once only when no valid protocol frame appears after two seconds. The module vendor specifies 5–10 seconds for the initial algorithm result and about 1.28 seconds for later updates. The gateway therefore targets 8 seconds of cumulative cold-start stabilization: time already spent in `/api/vitals/prepare` is deducted, while a user-started measurement always keeps at least 3 seconds for two update periods. A real contact/heart-rate signal opens a 12-second adaptive stabilization window. Two heart-rate and two SpO2 values must occur in the recent signal window; old isolated values cannot complete a session. If heart rate is already stable while SpO2 is still zero, one targeted 8-second SpO2 grace window is allowed. Sessions with no heart-rate signal are not extended. `communication_status=receiving_protocol_frames` distinguishes a healthy UART transport with zero algorithm values from `no_protocol_frames`. Heart rate, SpO2 and forehead temperature are all required for `complete`; blood pressure and HRV are never synthesized and do not delay completion. Each cold session sends `0x2A`, clears stale UART input, then sends `0x24`; a prepared session keeps the running algorithm and flushes only stale input. Cancellation, completion and read failure all stop the module with `0x2A`.

UART8 and GY-614 child output is retained per measurement under
`/userdata/qsm-vitals/logs/<session_id>-uart8.log` and
`/userdata/qsm-vitals/logs/<session_id>-gy614.log`. A missing GY-614 reader is
written to the latter with its expected path instead of being silently discarded.
The gateway process log remains `/userdata/qsm-vitals/logs/vitals-gateway.log`.

The session interface carries diagnostics end to end. `stable_core`, frame counts,
first-valid-frame positions, prewarm timing, SpO2 extension state and
`communication_status` remain visible through FastAPI. Metric provenance uses
`gy614_sensor`, `uart8_sensor`, `demo_fallback` and `history_fallback`; host-to-gateway
transport failures use `failure_reason=transport_error`, and a replaced session retains
`cancel_reason=replaced`. Normal cancellation uses `cancel_reason` only and leaves
`failure_reason` unset; a UART stop failure remains attached to the cancelled session
instead of being cleared.

Phase two adds a data-truth boundary without changing retry or timeout policy.
`spo2_source=demo_fallback` may still support an explicitly labelled live demo,
but that session is never written to `vitals_records` or marked for cloud sync.
Existing records carrying the legacy `SpO2-demo` marker are excluded from cloud
snapshots and from selection as the previous complete measurement.
Legacy inquiry vitals that exactly match one of those marked records are exposed
as a failed, quarantined demo without their numeric readings.
An unstable current session remains `failed`; the previous complete measurement
is exposed only through `historical_*` reference fields and is rendered separately
from the current result.

Phase three uses `failure_reason` as the terminal-facing presentation contract.
One or two consecutive `transport_error` results keep the same session active and
poll it again after 700 ms; any healthy status response resets that failure count.
Only an explicit user cancellation or a third consecutive communication failure
causes the UI to request board-side cancellation. A transient browser-to-host
request failure follows the same policy and no longer cancels the board session
immediately. The cancellation request is latched per session so overlapping
cleanup cannot send it twice, and a late response whose `session_id` no longer
matches the active measurement is ignored. This phase does not change the
18-second measurement timeout, the 12-second contact stabilization window, the
one-time 8-second SpO2 grace window, or the UART8 start/stop/frame protocol.

The first deep-module extraction keeps the HTTP interface compatible while moving
host-side response modeling, data-truth checks, historical references and
persistence/sync effects into `backend/app/modules/vitals_session.py`. Its narrow
interface is `prepare / start / get / cancel`; `QsmClient` and the in-memory test
gateway are adapters at that seam. The browser module
`frontend/src/modules/vitalsSession.js` owns prewarm, start/poll/cancel lifecycle,
phase transitions, active-session identity, SpO₂ retry and embedded completion.
Its `vitalsSessionAdapter.js` dependency owns transient transport decisions and
one-shot cancellation, leaving the React page as a presentation caller. UART8 and GY-614 sampling remain inside the owned QSM
gateway adapter, so this extraction does not change the validated timing or frame
protocol.

## Supported adapter methods

- `health_check()`
- `get_qsm_status()`
- `read_vitals()`
- `read_full_vitals()`
- `read_temperature()`
- `start_vitals_session()`
- `get_vitals_session(session_id)`
- `cancel_vitals_session(session_id)`
- `get_device_status()`
- `dispense(slot, dry_run=False)`
- `audio_asr()`
- `audio_status()`
- `audio_speak()` calls the QSM offline TTS route used by local presentation mode and cloud-TTS fallback.
- `audio_beep()`

QSM camera proxy methods live in `services/qsm_camera_service.py`. Normal identity calls use `services/qsm_face_client.py`; `services/identity_service.py` only resolves identities already bound to service users. Unknown or historical unbound face subjects are reported during wake-time recognition. The separate dispense verification endpoint can create a clearly labelled local visitor only after the user explicitly selects face confirmation.

Fingerprint calls use `services/qsm_fingerprint_client.py`. The AS608 module stores fingerprint templates; SQLite stores only `template_id -> service_user_id`, last-seen time and match score. Existing board templates are never treated as identities unless they have a local binding. IDs 0-15 are reserved by default so the verified pre-existing board template is not overwritten.

The FF Camera microphone is captured on QSM by the dedicated port `8082` gateway. It auto-detects the ALSA `FF Camera`/`Camera` card and exposes real `S16_LE`, 16 kHz, mono PCM. The host ASR websocket consumes that stream directly, so browser microphone permissions and a host microphone are not required. Online mode streams PCM to Qwen realtime ASR. Local mode buffers one user-controlled utterance, converts it to float PCM and sends the complete request to the resident QSM Paraformer service on board port `6006` (host forward `18084`). Capture gain changes are forwarded to the QSM `Mic` mixer control. When the host closes a recording stream, the gateway now terminates its child `arecord` process immediately; a cancelled or failed request cannot retain the microphone for the former 600-second capture limit.

The speaker has two serialized playback paths behind `SpeechService`. Online Qwen realtime TTS writes 24 kHz PCM deltas to board port `19001` as they arrive. Local presentation mode calls QSM `/api/audio/speak`, where the board-local Sherpa-ONNX VITS model synthesizes and plays the utterance. Cloud synthesis failures use the same QSM fallback. Normal kiosk startup stops the retired board language-model process to reserve memory for ASR, TTS and peripherals.

WiFi strength comes from the host `iw ... link` dBm value. SIM strength comes from the QSM EC200A `AT+CSQ` response and is converted to dBm, percentage and 0-4 bars. The top bar therefore reflects each live link independently instead of assuming full signal.

The host SIM fallback is a routed USB link rather than an ADB-forwarded HTTP request. QSM `usb0` is the EC200A WAN, QSM `usb1` is the RNDIS link to host `usb0`, and `qsm_gateway/start_host_tether.sh` enables forwarding and NAT. The root-owned host helper assigns `192.168.77.2/24` and a metric-700 default route through `192.168.77.1`; WiFi remains the preferred lower-metric route. Install the helper once with `sudo sh scripts/install_qsm_tether_helper.sh`. Settings refuses to disable WiFi when this route cannot be verified.

By default the app uses the real cabinet-control path: `DISPENSE_DRY_RUN=false` and `ENABLE_REAL_DISPENSE=1`. One tap in the 取药确认 modal starts fingerprint or face confirmation and automatically continues to the gateway dispense call after identity and optional today-plan ownership checks succeed. Successful real actions are written to the family pickup record; dry-run and failed calls stay out of that user-facing list. `REAL_DISPENSE_TEST_SLOT` is optional and can limit physical tests to one safe slot. For non-physical checks, use `POST /api/qsm/dispense/dry-run` or temporarily set `DISPENSE_DRY_RUN=true`.

`scripts/deploy_qsm_gateway.sh` can install the AS608 payload when it finds `QSM368ZP-AS608-offline-deploy(1).zip` at the repository root, or when `QSM_FINGERPRINT_BUNDLE` points to the package. Template IDs `0..15` remain reserved; host-created bindings start at 16. Fingerprint templates stay inside AS608 and face features stay on QSM. The host stores only local subject mappings, match counters, last-seen timestamps and dispense audit records.

The gateway also exposes best-effort `/api/fingerprint/standby` and `/api/fingerprint/wake`. The verified AS608-compatible unit reports Aura LED command `0x35` as unsupported, so complete power-off requires a hardware-controlled `Vt/WAK` connection; the four UART/USB-TTL data and power wires cannot provide software power gating.

## Device endpoints

```text
POST /api/vitals/read-all
POST /api/vitals/session/start
GET  /api/vitals/session/{session_id}
POST /api/vitals/session/{session_id}/cancel
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
POST /api/fingerprint/standby
POST /api/fingerprint/wake
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

### Physical dispense idempotency

The medicine-page manual route sends a non-empty `operation_id` to the board
`/api/dispense` boundary. The station gateway patch serializes each operation by
that ID and atomically persists `reserved -> sent -> final` around the original
UART/GPIO call. Replaying the same normalized slot, quantity and control code
returns the stored result without another pulse; reusing an ID with different
content fails. A stale `reserved`/`sent` record, corrupt state, transport loss or
missing final result is reported as `result_unknown=true` and `retry_safe=false`.
The host surfaces that as `RESULT_UNKNOWN`; neither layer automatically retries.

Scheduled-plan and AI-inquiry cabinet actions use the same replay contract.
A plan action persists one board ID on the plan before the first QSM call and
reuses it while the result is in progress or unknown, including across midnight
and process restarts. A known failure may reserve a new action; a successful
action marks the persisted ID complete with the plan. An inquiry action derives
its ID from the server-owned inquiry session, selected
option and medicine index; a real inquiry action without that identity fails
closed before QSM. Transport uncertainty is preserved in both the dispense and
inquiry responses as `result_unknown=true` and `retry_safe=false`, with explicit
instructions to verify the cabinet on site and not retry automatically. A plan is
not completed while its result is unknown.

Administrator cabinet tests require a client `request_id`. The admin UI stores one
pending ID per slot in session storage before sending the request and keeps it when
the HTTP or cabinet result is uncertain, so a replay reaches QSM with the same
`admin-*` operation ID. A known completion clears that pending ID. Admin responses
also expose `result_unknown` and `retry_safe`, and the audit ledger records an
uncertain action as `unknown` rather than an ordinary failure.

The physical dispense HTTP request is sent once using one fixed body encoding;
an empty response, disconnect, invalid response or HTTP failure becomes
`result_unknown` and is never retried with a second encoding. The board also
serializes all operation IDs at one hardware lock and returns
`hardware_unavailable` rather than simulated success when neither UART5 nor a
slot GPIO exists. Physical smoke is still a separate, supervised step and is
never run by automated tests.

## AI And Recognition

Medicine scan follows this order:

- reuse the latest real QSM stream frame, or request one QSM still frame;
- decode a local barcode if a decoder is installed or configured;
- call Qwen visual recognition if `DASHSCOPE_API_KEY` or `DASHSCOPE_API_KEY_FILE` is configured;
- return `manual_required` if recognition still fails.

Inquiry AI follows this order:

- call the configured DeepSeek-compatible cloud endpoint from the host in both terminal presentation modes;
- if the key is missing, connectivity fails or the cloud response is invalid, expose no
  candidate, retain emergency hard-guard behavior and return a natural retry
  prompt without showing transport or fallback terminology. Deterministic rules
  do not use character-similarity or keyword scoring to invent a candidate.

When heat exposure or suspected heat illness is mentioned, the online request
also includes current Chengdu weather from Open-Meteo as supporting context.
Weather cannot establish a diagnosis and never replaces heart rate, blood oxygen
or forehead temperature.

The retired board language-model assets are not part of the product route. See [`offline-ai.md`](offline-ai.md) for the cloud-only contract, rule fallback and diagnostic boundary.

## QSM face identity

`scripts/deploy_qsm_gateway.sh` starts the main gateway on board port `8080`, the face gateway on `8081`, and the FF Camera microphone gateway on `8082`. The face runtime reads `/dev/video23`, performs feature extraction/matching on QSM and stores its template database under `/userdata/qsm-face/data`. The host stores only the opaque face subject to service-user mapping.

The deploy script also installs `patch_station_gateway.pl` before restarting the main gateway. The guarded patch makes an empty client request exit its forked child and makes an MJPEG child exit after the shared camera producer stops. This prevents stale preview workers from retaining the camera when the UI switches from live preview to face matching.

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
