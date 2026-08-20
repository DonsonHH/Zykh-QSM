# Architecture

## System boundary

`zykh_station_app` is the local master application. It owns the UI, station workflow, local persistence, safety rules, inquiry records, dispense records, local sync queue, medicine recognition, service-user identity mapping and medicine-to-cabinet projection. QSM368ZP-WF remains an external gateway for camera/face processing, vitals, audio, three-category-cabinet light control and offline speech synthesis, and is accessed only through the backend service boundary. Both presentation modes use the cloud inquiry model; the legacy board language-model assets are diagnostic-only and are stopped by the normal kiosk launch path.

SQLite is initialized with the local operational tables needed by the terminal:
medicines, dispense records, device actions, inquiry records, vitals records,
service users, today plans, identity assertions, one-time medicine safety checks,
an append-only safety-event outbox and sync state. `today_plans` stores
service-user and medicine IDs, while display names remain snapshots; invalid
legacy name-only rows and plans owned by archived people are quarantined with
`archived=1` during migration instead of being deleted or appearing as valid plans.

Cabinet v2 uses two identities at different boundaries. `hardware_slot=1..23`
remains the durable logical inventory key in SQLite, records and CloudBase. A
local catalog maps each stable medicine ID to one physical `cabinet_id=1..3`
immediately before presentation or hardware execution. The physical ID is not a
replacement database key and is not synchronized to CloudBase. Missing mappings
fail closed. The three current category labels are local configuration proposals,
not evidence that the real cabinet has already been stocked that way. No file in
`cloudbase/` or cloud schema changes for this v2.0.0 hardware projection.

## Backend layers

- `main.py`: app factory, middleware, router registration and startup initialization.
- `routers/`: HTTP endpoints and request/response schemas.
- `modules/`: deep application modules. `VitalsSessionModule` owns cross-boundary
  provenance/data-truth gates, historical references and persistence/sync policy
  behind `prepare / start / get / cancel`; the QSM adapter owns gateway-specific
  response normalization before that boundary.
- `services/`: station, dashboard, QSM gateway, inquiry, records and sync use cases.
  `ManualMedicationAccessModule` is a deep application module kept here for
  compatibility with the existing service layout; its public surface is only
  `assess(command)` and `confirm(command)`.
- `repositories/`: SQLite persistence adapters. Approximate and filled terminal
  vitals use the normal `vitals_records` path, with metric provenance,
  `measurement_quality` and `completion_reason` carried into cloud sync. The
  legacy `demo_vitals_records` table remains only for old-row migration.
- `schemas/`: Pydantic input/output contracts.
- `core/`: constants and safety language.

No route should call the peripheral gateway directly. Vitals session routes call `modules/vitals_session.py`, which uses `services/qsm_client.py` as its production gateway adapter; an in-memory adapter drives the same module interface in tests. General non-session gateway behavior goes through `services/qsm_client.py`; camera streaming and face identity go through `services/qsm_camera_service.py` and `services/qsm_face_client.py`.

## QSM gateway adapter

The gateway adapter supports:

- `QSM_MODE=mock`: stable local demo data.
- `QSM_MODE=real`: HTTP calls to the main gateway at `QSM_BASE_URL` (`18080`), the face gateway at `QSM_FACE_BASE_URL` (`18081`), and the FF Camera microphone gateway at `QSM_MIC_BASE_URL` (`18082`).
- legacy QSM llama.cpp tooling may use board port `8083` and host port `18083` during explicit diagnostics, but the production application never starts, probes or falls back to it.
- the QSM sherpa-onnx Paraformer ASR service listens on board port `6006` and is forwarded to `18084`; local recognition uploads one complete utterance and returns one final transcript.
- online TTS sends incremental 24 kHz PCM to the QSM speaker stream on `19001`; local presentation mode calls the QSM `/api/audio/speak` route, which runs the bundled Sherpa-ONNX VITS assets on the board and plays the generated WAV through the managed QSM audio path.
- structured failure responses when the gateway is unavailable.
- `DISPENSE_DRY_RUN=false` and `ENABLE_REAL_DISPENSE=1` as the real-device default,
  with explicit identity confirmation after biometric matching, optional
  `REAL_DISPENSE_TEST_SLOT` (legacy name; v2 value is physical cabinet `1..3`),
  and a local audit record for every cabinet-light action.
  Manual-inventory calls carry a stable `operation_id`; the board reserves it
  before the `/dev/ttyACM0` 115200 text exchange, replays the stored result for
  the same `cabinet_id + quantity` payload and never retries an
  in-flight/ambiguous illuminate operation. Success requires exact `CABINET n`
  ACK and `STATUS CABINET n`; after the inventory-confirmation prompt completes,
  the UI automatically sends and verifies `OFF`.

Real mode failure must not break the dashboard. The backend returns a normal `/api/qsm/status` response with `connected=false`; the terminal UI only shows a user-facing device state such as “暂不可用”. Communication, startup and device failures are not replaced by filled data. The optional core-vitals completion applies only after a started session returns a valid real temperature and an eligible hand-signal stabilization failure. It retains any available sensor readings, fills only missing core metrics, records provenance and quality in `vitals_records`, and follows the normal sync path.

Stage six adds business-facing QSM action endpoints:

- `/api/vitals/read-all`: QSM gateway vitals read with configured path fallback.
- `/api/camera/stream` and `/api/qsm/camera/capture`: QSM camera stream and still-capture proxy.
- `/api/qsm/dispense/dry-run`: local dry-run integration check retained for non-physical tests.
- `/api/qsm/cabinet-light/off` and `/api/qsm/cabinet-light/status`: explicit all-off control and read-only state verification.
- `/api/qsm/capabilities`: device capability summary for UI decisions.
- `/api/audio/asr`, `/api/audio/beep`: QSM audio gateway actions. Online TTS is generated in the cloud and streamed through the QSM PCM path; local presentation mode uses the enabled board-side `/api/audio/speak` route.
- `/api/audio/host/status`, `/api/audio/host/mic-volume` and `/api/audio/asr/realtime`: QSM FF Camera microphone status, capture-gain control and realtime PCM-to-ASR bridge.
- `/api/dispense/confirm`: safety-confirmed physical cabinet-light call when dry-run is disabled.

Face templates remain on QSM. SQLite stores only opaque face subjects linked to service-user IDs; inquiry and dispense records keep the resolved service-user identity. Recognition requires temporal agreement across multiple frames and never creates a profile from an unknown face.

Stage seven adds a device check workflow:

- `services/device_check_service.py` aggregates gateway, vitals, QSM camera and cabinet-light state, including a live read-only `STATUS` probe when real control is enabled.
- `/api/device/check` returns HTTP 200 with warnings and recommendations when real hardware is unavailable.
- `cabinet_light_ok`, `cabinet_light_status` and `cabinet_light_cabinet_id` distinguish a verified all-off state, one cabinet still lit and an unavailable controller; configuration alone is not a readiness signal.
- `scripts/check_devices.sh` performs command-line pre-demo checks and reports `OK`, `WARN` and `FAIL` lines without stopping the app.

Phase eight switches the runtime defaults to real-device first:

- QSM camera preview and capture use the real gateway path;
- medicine scan requires barcode decode, visual recognition or manual confirmation;
- records and dashboard values come from SQLite instead of fixed page constants;
- sync reports `未配置` until a real cloud endpoint is configured;
- inquiry uses the configured DeepSeek-compatible cloud endpoint in both terminal
  presentation modes. If the cloud model is unavailable, deterministic rules keep
  the session retryable and cannot generate a medicine candidate; transport and
  fallback terminology stays out of terminal-facing copy.

## AI routing

`services/ai_service.py` owns cloud routing, open case extraction, conversation
actions and candidate ranking. Legacy `services/local_ai_client.py` remains only
for explicit diagnostics and is not part of the production inquiry path. The
cloud model decides how to describe the case, what single question to ask next,
whether vitals are needed and whether recent history is semantically related. It
can rank only IDs admitted by the hard-safe pool and may return no candidate.

For online environment-sensitive complaints such as heat exposure, the service
can attach current Chengdu weather from Open-Meteo to the model request. This is
supporting context only and cannot establish a cause or replace measured vitals.
The two presentation modes share this model path. Local presentation mode changes
the status icon, mini-program realtime sync and speech route only; it does not
select a second language model or a second clinical schema.

Deterministic code is deliberately narrower: it intercepts non-negotiable danger
signals, may raise but never lower model risk, excludes expired, unavailable,
non-OTC or contraindicated medicines, and revalidates the selected option before
the existing dispense service runs. Candidate retrieval also uses reviewed
spoken-term equivalents and catalog-use mappings to bridge colloquial wording to
the fixed 23 logical medicine identities; this only narrows what the model sees and never
bypasses availability, prescription-plan, contraindication or expiry checks.
After a completed low-risk analysis, a focused eligible OTC pool can also supply
one or two observation-labelled alternatives when the model returns no option or
only one option. This deterministic fallback is presentation and selection
continuity, not a second diagnosis engine: it uses only the already-focused pool,
prefers a different category for the second option, and remains disabled for
provider failure, assessments whose every listed cause still needs exclusion,
prescription-plan items and every hard safety block. A secondary cause marked
`needs_exclusion` does not erase a separate `possible` or `more_likely`
symptom-scoped option; its monitoring and seek-care advice remains visible.
Extracted observations keep open, user-led
symptom concepts rather than a fixed symptom taxonomy. A bounded dialogue-policy
layer classifies the model's proposed question into decision topics so it can
enforce one question per turn, the four-question budget and no-repeat rules; it
uses a small fallback-question set only when the proposal is missing or unsafe.
The cloud Responses route and its cloud Chat Completions fallback rank the
hard-safe pool against the same semantic output contract and validator. The model
must return the complete `assessment + options` object and may only select catalog
IDs. Deterministic rules do not supply or impersonate a missing
model assessment: on an unavailable or invalid final rank, the session remains
retryable and exposes no candidate. Rules remain available only for bounded
dialogue continuity and non-negotiable danger interception.

Deployment and lifecycle details are documented in [`offline-ai.md`](offline-ai.md).

## Frontend layers

- `App.jsx`: top-level shell, current page state, idle timeout, active-user lifecycle and toast feedback.
- `pages/`: Home, Medicines, Inquiry, Records and Scan pages.
- `components/`: terminal layout primitives, touch controls and the lightweight system-check modal.
- `modules/`: browser-side deep modules. `vitalsSession.js` owns prewarm, start/poll/cancel lifecycle, phase transitions, active-session identity, SpO₂ retry and embedded inquiry completion.
- `adapters/`: browser-side transport adapters. `vitalsSessionAdapter.js` supplies transient-failure decisions and one-shot board cancellation to the session module.
- `api/`: fetch client, dashboard API and mock fallback data.
- `styles/`: token-driven terminal styling.

The medicine and administrator views consume the local three-cabinet projection,
while domain checks and sync continue to use medicine ID plus logical
`hardware_slot`. The pickup modal describes a light and manual door opening. One
initial action runs identity and safety checks and, when they pass, continues to
illumination; after the “还有药吗” prompt completes it automatically sends `OFF`.
It never infers that a successful light ACK proves a door opened.

`Vitals.jsx` consumes the session module state and intent methods as a presentation caller; it does not call the vitals gateway or own polling/session refs.

The terminal is designed around a landscape 11-inch touch display. The kiosk launcher keeps the active display mode and applies a process-scoped `2x` Chromium device scale by default; exiting Chromium removes that scale without changing the desktop display configuration.

The root terminal opens on a wake screen. After a configurable idle period (`VITE_IDLE_TIMEOUT_SECONDS`, default 90), the app clears the active identity and returns to that screen. Face recognition is not run globally: inquiry and dispense start their own identification flow, show the matched person, and require an explicit user confirmation before continuing.

## Safety boundary

The server classifies cabinet-light work as PLAN, INQUIRY or MANUAL_INVENTORY. PLAN and
INQUIRY retain their existing credentials and deterministic revalidation.
MANUAL_INVENTORY cannot call the shared dispense endpoint directly: a registered
face/fingerprint assertion must first produce a short-lived, one-time `PASSED`
check bound to person generation/revision, medicine review fingerprint, display
slot, logical hardware slot, local cabinet mapping, exact stock and expiry. `BLOCKED`, `CHECK_FAILED`, unconfirmed
or changed checks call QSM zero times.

The check state and physical state are separate. A confirmed check may become
`DISPENSED`, `HARDWARE_FAILED` or `RESULT_UNKNOWN`; the last value is persisted
before returning and is never automatically retried. High-risk inquiry outcomes
remain blocked from 取药确认. `REAL_DISPENSE_TEST_SLOT` can restrict a controlled
physical smoke to one agreed cabinet ID `1..3`.

Safety events are written transactionally to a local append-only outbox and sent
only when CloudBase advertises `medicationSafetyEvents=v1`. They are not dispense
records and never participate in snapshot finalization. Caregiver reads are
membership- and person-scope-authorized; cloud/mobile code has no cabinet-open,
cabinet-light, approval or unblock action.
Each check owns one stable event ID: terminal assessment failures are queued
immediately, while a passed check is queued only after its dispense outcome is
known. This prevents the assessment and cabinet result from appearing as two
caregiver records.
