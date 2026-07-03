# Architecture

## System boundary

`zykh_station_app` is the local master application. It owns the UI, station workflow, local persistence, rules fallback, inquiry records, dispense records, local sync queue and host-side camera recognition. QSM368ZP-WF remains an external peripheral gateway for vitals, audio and cabinet-control peripherals, and is accessed only through the backend service boundary.

SQLite is initialized with the local operational tables needed by the terminal: medicines, dispense records, device actions, inquiry records, vitals records, service users, today plans and sync state.

## Backend layers

- `main.py`: app factory, middleware, router registration and startup initialization.
- `routers/`: HTTP endpoints and request/response schemas.
- `services/`: station, dashboard, QSM gateway, inquiry, records and sync use cases.
- `repositories/`: SQLite persistence adapters.
- `schemas/`: Pydantic input/output contracts.
- `core/`: constants and safety language.

No route should call the peripheral gateway directly. Gateway-facing behavior goes through `services/qsm_client.py`. Host-side camera behavior goes through `services/local_camera.py`.

## QSM gateway adapter

The gateway adapter supports:

- `QSM_MODE=mock`: stable local demo data.
- `QSM_MODE=real`: HTTP calls to `QSM_BASE_URL`, default `http://127.0.0.1:18080`.
- structured failure responses when the gateway is unavailable.
- `DISPENSE_DRY_RUN=true` as the safe default, with a separate `ENABLE_REAL_DISPENSE=1` gate for controlled physical dispense tests.

Real mode failure must not break the dashboard. The backend returns a normal `/api/qsm/status` response with `connected=false`; the terminal UI only shows a user-facing device state such as “暂不可用”. Failed real calls are not replaced by fake success data.

Stage six adds business-facing QSM action endpoints:

- `/api/vitals/read-all`: QSM gateway vitals read with configured path fallback.
- `/api/qsm/camera/capture`: stable scan action endpoint backed by host-side camera service.
- `/api/qsm/dispense/dry-run`: local dry-run integration check retained for non-physical tests.
- `/api/qsm/capabilities`: device capability summary for UI decisions.
- `/api/audio/asr`, `/api/audio/speak`, `/api/audio/beep`: QSM audio gateway actions.
- `/api/dispense/confirm`: safety-confirmed physical gateway call when dry-run is disabled.

The camera endpoint name is kept for UI compatibility, but it does not proxy to the gateway camera path in the current hardware split.

Stage seven adds a device check workflow:

- `services/device_check_service.py` aggregates gateway, vitals, host camera and dry-run state.
- `/api/device/check` returns HTTP 200 with warnings and recommendations when real hardware is unavailable.
- `scripts/check_devices.sh` performs command-line pre-demo checks and reports `OK`, `WARN` and `FAIL` lines without stopping the app.

Phase eight switches the runtime defaults to real-device first:

- host camera capture uses `LOCAL_CAMERA_MODE=real`;
- medicine scan requires barcode decode, visual recognition or manual confirmation;
- records and dashboard values come from SQLite instead of fixed page constants;
- sync reports `未配置` until a real cloud endpoint is configured;
- cloud AI uses a DeepSeek-compatible endpoint when a key is present, otherwise the result is clearly marked as local fallback.

## Frontend layers

- `App.jsx`: top-level shell, current page state and toast feedback.
- `pages/`: Home, Medicines, Inquiry, Records and Scan pages.
- `components/`: terminal layout primitives, touch controls and the lightweight system-check modal.
- `api/`: fetch client, dashboard API and mock fallback data.
- `styles/`: token-driven terminal styling.

The terminal is designed around a 1280x720 landscape canvas for an 11-inch touch display.

## Safety boundary

High-risk inquiry outcomes remain blocked from 取药确认. Real dispense testing must use an agreed safe slot and must keep the confirmation step plus local audit record.
