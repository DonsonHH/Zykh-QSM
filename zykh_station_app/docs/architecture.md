# Architecture

## System boundary

`zykh_station_app` is the local master application. It owns the UI, station workflow, local persistence, safety rules, inquiry records, dispense records, local sync queue, medicine recognition and service-user identity mapping. QSM368ZP-WF remains an external gateway for camera/face processing, vitals, audio, cabinet control and the offline language model, and is accessed only through the backend service boundary.

SQLite is initialized with the local operational tables needed by the terminal: medicines, dispense records, device actions, inquiry records, vitals records, service users, today plans and sync state.

## Backend layers

- `main.py`: app factory, middleware, router registration and startup initialization.
- `routers/`: HTTP endpoints and request/response schemas.
- `services/`: station, dashboard, QSM gateway, inquiry, records and sync use cases.
- `repositories/`: SQLite persistence adapters.
- `schemas/`: Pydantic input/output contracts.
- `core/`: constants and safety language.

No route should call the peripheral gateway directly. General gateway behavior goes through `services/qsm_client.py`; camera streaming and face identity go through `services/qsm_camera_service.py` and `services/qsm_face_client.py`.

## QSM gateway adapter

The gateway adapter supports:

- `QSM_MODE=mock`: stable local demo data.
- `QSM_MODE=real`: HTTP calls to the main gateway at `QSM_BASE_URL` (`18080`), the face gateway at `QSM_FACE_BASE_URL` (`18081`), and the FF Camera microphone gateway at `QSM_MIC_BASE_URL` (`18082`).
- the QSM llama.cpp service listens on board port `8083` and is forwarded to `LOCAL_AI_BASE_URL` (`18083`).
- the QSM sherpa-onnx streaming ASR service listens on board port `8084` and is forwarded to `18084`.
- online TTS sends incremental 24 kHz PCM to the QSM speaker stream on `19001`; offline TTS uses a resident board-local model service on `19002`.
- structured failure responses when the gateway is unavailable.
- `DISPENSE_DRY_RUN=false` and `ENABLE_REAL_DISPENSE=1` as the real-device default, with a safety checkbox, optional `REAL_DISPENSE_TEST_SLOT`, and local audit record for every cabinet action.

Real mode failure must not break the dashboard. The backend returns a normal `/api/qsm/status` response with `connected=false`; the terminal UI only shows a user-facing device state such as “暂不可用”. Failed real calls are not replaced by fake success data.

Stage six adds business-facing QSM action endpoints:

- `/api/vitals/read-all`: QSM gateway vitals read with configured path fallback.
- `/api/camera/stream` and `/api/qsm/camera/capture`: QSM camera stream and still-capture proxy.
- `/api/qsm/dispense/dry-run`: local dry-run integration check retained for non-physical tests.
- `/api/qsm/capabilities`: device capability summary for UI decisions.
- `/api/audio/asr`, `/api/audio/speak`, `/api/audio/beep`: QSM audio gateway actions.
- `/api/audio/host/status`, `/api/audio/host/mic-volume` and `/api/audio/asr/realtime`: QSM FF Camera microphone status, capture-gain control and realtime PCM-to-ASR bridge.
- `/api/dispense/confirm`: safety-confirmed physical gateway call when dry-run is disabled.

Face templates remain on QSM. SQLite stores only opaque face subjects linked to service-user IDs; inquiry and dispense records keep the resolved service-user identity. Recognition requires temporal agreement across multiple frames and never creates a profile from an unknown face.

Stage seven adds a device check workflow:

- `services/device_check_service.py` aggregates gateway, vitals, QSM camera and cabinet-control state.
- `/api/device/check` returns HTTP 200 with warnings and recommendations when real hardware is unavailable.
- `scripts/check_devices.sh` performs command-line pre-demo checks and reports `OK`, `WARN` and `FAIL` lines without stopping the app.

Phase eight switches the runtime defaults to real-device first:

- QSM camera preview and capture use the real gateway path;
- medicine scan requires barcode decode, visual recognition or manual confirmation;
- records and dashboard values come from SQLite instead of fixed page constants;
- sync reports `未配置` until a real cloud endpoint is configured;
- cloud AI uses a DeepSeek-compatible endpoint when reachable; failures route to the real QSM Qwen3.5 model, then to deterministic safety rules only if the model process is also unavailable.

## AI routing

`services/ai_service.py` owns cloud-first routing, true SSE forwarding and output guards. Cloud thinking can improve answer selection, but reasoning tokens are never exposed to the UI. `services/local_ai_client.py` is the narrow OpenAI-compatible streaming adapter for QSM llama.cpp; startup prewarming primes its stable short prompt prefix. The deterministic `rules_engine.py` remains authoritative for emergency interception, final risk escalation, contraindications and dispense eligibility. Model output may add a summary or follow-up, but cannot lower rule risk or assert that medicine use is safe.

Deployment and lifecycle details are documented in [`offline-ai.md`](offline-ai.md).

## Frontend layers

- `App.jsx`: top-level shell, current page state, idle timeout, active-user lifecycle and toast feedback.
- `pages/`: Home, Medicines, Inquiry, Records and Scan pages.
- `components/`: terminal layout primitives, touch controls and the lightweight system-check modal.
- `api/`: fetch client, dashboard API and mock fallback data.
- `styles/`: token-driven terminal styling.

The terminal is designed around a 1280x720 landscape canvas for an 11-inch touch display.

The root terminal opens on a wake screen. After a configurable idle period (`VITE_IDLE_TIMEOUT_SECONDS`, default 90), the app clears the active identity and returns to that screen. A wake interaction starts a new QSM face check; until a user is confirmed, the dashboard requests the explicit unconfirmed view and does not expose another household member's medication plan.

## Safety boundary

High-risk inquiry outcomes remain blocked from 取药确认. Physical cabinet actions must keep the confirmation step plus local audit record; `REAL_DISPENSE_TEST_SLOT` can be set when a run must be restricted to one agreed safe slot.
