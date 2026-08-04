# API

Base URL during development:

```text
http://127.0.0.1:8000
```

## Endpoints

### GET /api/health

Returns service, database, QSM mode and cabinet-control mode.

### GET /api/status

Returns top-level station status for the terminal shell:

- network mode;
- AI mode;
- peripheral device status;
- sync status;
- cabinet-control mode;
- status chips.

### GET /api/site

Returns the home terminal profile displayed by the terminal.

### POST /api/site

Updates the station profile fields used by the terminal.

### GET /api/dashboard

Returns the homepage data assembled from local SQLite records and gateway state:

- site profile;
- top status chips;
- today medication summary;
- emergency inquiry summary;
- quick actions;
- bottom station stats;
- safety notice.

### GET /api/qsm/status

Returns real or mock peripheral gateway status. Defaults to real mode.

### GET /api/device/check

Returns the demonstration readiness check:

- QSM mode and connection state;
- QSM base URL;
- QSM status and vitals readiness;
- QSM camera and face-service readiness;
- dispense safety flag;
- errors, warnings and recommendations.

The endpoint always returns HTTP 200 for expected missing-device cases so the terminal UI can degrade gracefully.

### GET /api/medicines

Returns the home medicine list and available categories. Each medicine includes
`indications`, `dosage`, `contraindications`, `guidance_source` and
`guidance_review_required`. When an administrator changes a medicine name,
manufacturer, barcode or category, the backend attempts a structured cloud
guidance refresh. Generated guidance remains review-required and must be checked
against the physical package leaflet.

### GET /api/medicines/{medicine_id}

Returns a single medicine detail.

### POST /api/dispense/confirm

Requires the safety notice confirmation flag and writes a local 取药确认 record. By default it calls the QSM dispense path when `DISPENSE_DRY_RUN=false`, `ENABLE_REAL_DISPENSE=1`, and request body `confirm_real_dispense=true`. `REAL_DISPENSE_TEST_SLOT` is optional; when configured, only the matching slot can open.

For an unregistered or unidentified face, the frontend sends
`archive_identity_snapshot=true` after explicit guest confirmation. A successful
real dispense then retains a small preview frame for the protected administrator
overview. Registered users and dry-run actions do not create this photo archive;
photo conversion failure never blocks an already confirmed cabinet action.

### GET /api/dispense/records

Returns local dispense confirmation records.

### POST /api/inquiry/evaluate

Compatibility entry for one-shot AI inquiry. It reuses the model-led case
interpreter, deterministic hard-risk guardrails and the hard-safe medicine pool
used by the session API.

### POST /api/inquiry/sessions

Creates a persisted inquiry session after identity is confirmed once. The response contains `stage`, `reply`, `next_action`, extracted evidence and current safety decision.

### GET /api/inquiry/sessions/{session_id}

Restores one inquiry session with messages, identity, vitals snapshot and result.

### POST /api/inquiry/sessions/{session_id}/turn

Adds one speech transcript. The selected cloud or local model reads the full
conversation, profile, vitals and recent natural-language case summaries. It
returns open evidence-backed observations, a natural response, semantic risk
signals and one `ask|measure_vitals|analyze|escalate|end` action. There is no
fixed symptom taxonomy, fixed field order or fixed turn count. The model may
choose `measure_vitals` only after it has formed a meaningful chief complaint
and only when core vitals materially affect the next decision. The frontend
finishes the spoken guidance, pauses for 2.2 seconds, then renders the vitals
tool inside the inquiry flow. It does not navigate away or transfer results
through browser storage.

Before recommendation, deterministic code can only raise risk for non-negotiable
danger signals and builds a pool filtered by stock, expiry, OTC eligibility and
absolute contraindications. The model may choose at most one primary and one
alternative from that pool, or choose none. If both model routes are unavailable
or return invalid structure, the session remains retryable, returns no candidate
and does not expose connection or fallback terminology in its user-facing reply.
Environment-sensitive cloud requests may include current Chengdu weather as
supporting context; it cannot replace measured vitals or establish a diagnosis.

### POST /api/inquiry/sessions/{session_id}/vitals

Returns one vitals tool event to the same inquiry session. `status=complete`
requires `temperature`, `heart_rate` and `spo2`; optional blood-pressure,
respiratory-rate and HRV values do not block completion. `status=failed` and
`status=cancelled` may omit measurements and include `error_message`. All three
outcomes resume the same model conversation, while hard-risk checks run before
the model when complete core vitals are available.

### POST /api/inquiry/sessions/{session_id}/treatment/confirm

Confirms exactly one mutually exclusive treatment option. The request contains only `option_id` and `confirmed_safety_notice`; medicine IDs and cabinet slots are never accepted from the frontend. Immediately before any cabinet action, the backend recalculates risk, contraindications, expiry, stock and current OTC eligibility. If the displayed option changed, the request is rejected with `409` and no cabinet is opened. A successful confirmation executes the selected option through the existing `DispenseService`, records each action and rejects duplicate submissions.

### GET /api/inquiry/{inquiry_id}

Returns one inquiry result.

### GET /api/inquiry/records

Returns recent inquiry results.

### GET /api/records/summary

Returns record-page counters. `local_record_count` includes only successful real dispense actions; dry-run and failed device actions remain available to protected diagnostics but are not counted as family pickup records.

### GET /api/records/recent

Returns a compact list of successful real family pickup records. Each item includes `target_user_type=registered|guest`; guest rows are explicitly labelled as tourists in the terminal UI.

### GET /api/records/today-plans

Returns only plans due on the current date. Plan responses include `schedule_type` (`daily`, `interval`, `weekly`), `interval_days`, ISO weekday values in `weekdays`, `start_date`, `last_action_date`, `due_today`, `next_due_date` and a display-ready `frequency_label`.

### GET /api/sync/status

Returns local sync state. If no cloud sync endpoint is configured, the state is `未配置` with pending local records.

### POST /api/sync/run

Attempts a configured cloud sync. If no endpoint is configured, it returns HTTP 200 with a `未配置` message and does not mark records as synced.

### GET /api/qsm/vitals

Reads vitals through the QSM adapter and stores successful/failed readings locally. Real mode tries all configured vitals paths and returns HTTP 200 with `status=unavailable` when the peripheral gateway is unreachable.

### POST /api/qsm/camera/capture

Compatibility endpoint for the Scan page. It calls the QSM camera path and returns a structured real-device error on failure; it does not create fake medicine results.

### POST /api/qsm/dispense/dry-run

Runs a dry-run dispense integration check and writes a local dry-run record. Request body:

```json
{
  "slot": "B02",
  "medicine_id": "lianhua-qingwen",
  "quantity": 1,
  "reason": "联调验证"
}
```

The response always keeps `dry_run=true`.

### GET /api/qsm/capabilities

Returns current peripheral capability states:

- camera;
- vitals;
- dispense;
- voice;
- QSM connection state;
- mode.

### POST /api/vitals/session/start

Starts a QSM measurement session. A successful response requires `hardware_started=true`, which is returned only after the board writes UART start byte `0x24`.

### GET /api/vitals/session/{session_id}

Returns the real device stage: `starting`, `waiting_finger`, `stabilizing`, `complete`, `failed` or `cancelled`. `complete` requires heart rate, SpO2 and forehead temperature; auxiliary values are optional.

Session responses preserve device diagnostics instead of collapsing every failure
into one message:

- `stable_core` and `communication_status` distinguish stable measurements,
  healthy UART traffic with zero algorithm values, and gateway transport loss;
- `valid_frame_count`, `contact_frame_count`, `heart_rate_frame_count`,
  `spo2_frame_count`, `first_heart_rate_frame` and `first_spo2_frame` describe
  the received sample window;
- `prewarmed`, `prewarm_age`, `minimum_measurement_seconds` and
  `spo2_stabilization_extended` describe session timing decisions;
- `temperature_source`, `heart_rate_source` and `spo2_source` distinguish
  live sensors, demo fallback and historical fallback;
- `failure_reason` provides a stable machine-readable failure category such as
  `no_finger`, `no_protocol_frames`, `temperature_unavailable`,
  `transport_error` or `session_not_found`, while `error_message` remains the
  user-facing explanation;
- `cancel_reason=replaced` identifies a session stopped by a newer measurement.

### POST /api/vitals/session/{session_id}/cancel

Cancels the session and causes the board reader to send stop byte `0x2A`.

### POST /api/vitals/prepare

Legacy compatibility endpoint for the earlier shared background read flow.

### POST /api/vitals/read-all

Reads all available vitals through QSM. It prefers `QSM_VITALS_ALL_PATH`, then falls back to `QSM_VITALS_PATH` and `QSM_TEMP_PATH`.

The response keeps the original fields and adds optional UART8 integrated-sensor reference values:

```json
{
  "temperature": 36.3,
  "heart_rate": 78,
  "spo2": 98,
  "systolic_pressure": 118,
  "diastolic_pressure": 76,
  "respiratory_rate": 16,
  "hrv_sdnn": 42,
  "hrv_rmssd": 31,
  "body_temperature": 36.11,
  "reference_ready": true,
  "sensor_model": "UART8-vitals-24B"
}
```

Unavailable or zero placeholder values are returned as `null`. `body_temperature` is the UART module fingertip-temperature reference; `temperature` remains the GY-614 forehead temperature. Two non-zero heart-rate/SpO2 frames complete the core measurement early. When contact is present but SpO2 is still zero, the session remains active for the module's adaptive stabilization window instead of failing at the no-finger timeout. Optional blood-pressure and HRV reference frames never keep the sensor session open. `reference_ready` only becomes true after those optional reference samples are present. Auxiliary values are not diagnostic results and are never synthesized by the adapter.

### POST /api/camera/capture

Captures one image from the QSM camera. The response includes image availability, the host proxy image URL when available and a structured error on failure.

### GET /api/camera/stream

Proxies the QSM MJPEG stream to the browser and stores a recent real frame for automatic barcode checks. A brief gateway restart during face matching is retried before returning an error.

### POST /api/medicine/scan

Captures an image, tries local barcode decoding, then Qwen visual recognition when configured. If both fail, it returns `manual_required` instead of a fake match.

### GET /api/identity/status

Returns QSM face-runtime availability, enrolled sample count and host-side identity mapping count.

### POST /api/identity/resolve

Matches the current QSM camera face to an existing service user. Unknown faces are reported and do not silently create a profile.

### POST /api/identity/verify-dispense

Runs the explicit face-confirmation path from the dispense modal. A matched face returns the existing service user. When the user has selected face confirmation and no match exists, it creates a local visitor record, enrolls the QSM face template and returns that visitor. The host does not store the original face image or feature vector.

### POST /api/identity/enroll/{service_user_id}

Captures multiple QSM face samples and binds them to an existing service user. The protected administrator API wraps this action for the debug console.

### GET /api/fingerprint/status

Returns AS608 availability, module template count and host-side bound-user count. Templates 0-15 are reserved by default; host-managed enrollment starts at 16.

### POST /api/fingerprint/identify

Waits for a finger, matches the AS608 template and returns the bound service user. An unbound board template returns `status=unbound` and cannot open a cabinet.

### POST /api/fingerprint/standby and POST /api/fingerprint/wake

Best-effort AS608 indicator control used when entering or leaving the idle screen. Modules that do not implement Aura LED command `0x35` return HTTP 200 with `status=unsupported`; identity functions remain available.

### POST /api/fingerprint/enroll/{service_user_id}

Guides two placements of the same finger, stores the template in AS608 and stores only the template-to-user mapping in SQLite.

### DELETE /api/fingerprint/{service_user_id}

Deletes the mapped AS608 template and local binding for the selected service user.

### POST /api/medicine/visual-recognize

Runs the visual recognition fallback against an existing image path.

### POST /api/audio/asr

Records 16 kHz mono audio on QSM and calls the resident offline Paraformer service. It returns recognized text, the model identifier and structured errors without requiring a cloud API key.

### POST /api/audio/speak

Speaks text through the QSM speaker. Online mode uses host-connected Qwen realtime TTS and streams 24 kHz PCM deltas immediately; local mode uses the host-resident Sherpa-ONNX TTS model and streams generated PCM to QSM. The response exposes `requested_mode`, `engine`, `offline`, `first_audio_ms` and `total_ms`. It never calls the QSM board-side TTS service.

### POST /api/audio/host/warmup

Loads the host offline voice model in advance. This is used by the kiosk startup script to remove first-use model-loading delay.

### WebSocket /api/audio/asr/realtime

Streams real FF Camera microphone PCM into Qwen realtime ASR while online. In local mode it keeps the same browser control channel, buffers audio until the user stops speaking, then sends the complete utterance to the resident QSM Paraformer recognizer. Cloud mode can emit partial transcripts; local mode emits one final transcript.

### GET /api/audio/status

Returns host offline TTS readiness, QSM playback status and resident Paraformer ASR status without exposing API keys to the terminal UI.

### POST /api/audio/beep

Calls the QSM beep path.

### POST /api/ai/chat

Uses the configured cloud endpoint first in `AI_MODE=auto`. A missing key,
failed connectivity probe or cloud request error automatically routes the
request to the QSM llama.cpp endpoint. Internal response sources distinguish the
route for diagnostics, while the terminal-facing response never displays
connection errors or fallback terminology. If both routes fail, the endpoint
returns a short natural retry prompt and no medicine candidate.

### GET /api/ai/status

Returns the selected AI mode, cloud configuration state and QSM offline-model health without exposing API keys.

### POST /api/ai/chat/stream

Streams actual provider tokens as server-sent `meta`, `delta`, optional `replace`, and `done` events. Cloud DeepSeek reasoning remains hidden while final text is streamed. The QSM llama.cpp route uses the same true-streaming contract; `/api/ai/warm-local` primes its reusable prompt cache after startup.

## Terminal settings

### `GET /api/settings/basic`

Returns the persisted user-adjustable settings together with current Wi-Fi, data-network and microphone availability. Data-network fields include `sim_operator`, `sim_operator_code` and `sim_phone_number` when the EC200A provides them.

### `PATCH /api/settings/basic`

Accepts a partial payload containing `wifi_enabled`, `sim_enabled`, `network_mode`, `speaker_volume`, `microphone_volume`, `display_brightness` or `idle_timeout_seconds`. Only submitted fields are applied. Hardware failures are returned in `warnings` without discarding the saved preference.

## Administrator debug API

`/api/admin/*` routes require an in-memory bearer session created by `POST /api/admin/session`. Sessions expire automatically and are stored by the frontend only in `sessionStorage`.

- `POST /api/admin/session`, `DELETE /api/admin/session`
- `GET /api/admin/overview`
- `GET /api/admin/logs?source=backend`
- `GET|POST|PATCH|DELETE /api/admin/users...`
- `POST|DELETE /api/admin/users/{id}/face`
- `POST|DELETE /api/admin/users/{id}/fingerprint`
- `GET|PATCH /api/admin/medicines...`
- `GET|POST|PATCH|DELETE /api/admin/today-plans...`
- `POST /api/admin/cabinet/{slot}/open`
- `POST /api/admin/system/action`

The browser cannot submit shell commands. System actions use a server-side allowlist and configured fixed commands. The UI uses a normal yes/no confirmation while the server still validates an internal operation token; every protected action creates an `admin_audit_records` entry. Log output is limited to an allowlist, updates only while the log page is mounted, and redacts API keys, bearer tokens and secrets.

Administrator today-plan create/update payloads accept `schedule_type`, `interval_days`, `weekdays` and `start_date`. A successful plan dispense is serialized per plan, validates the recognized person and medicine, and records `last_action_date` so recurring plans become pending again only on their next due date.
