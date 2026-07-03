# Architecture

## System boundary

`zykh_station_app` is the local master application. It owns the UI, station workflow, local persistence, rules fallback, inquiry records, dry-run records, local sync simulation and host-side camera recognition. QSM368ZP-WF remains an external peripheral gateway for vitals, audio and cabinet-control peripherals, and is accessed only through the backend service boundary.

SQLite is initialized through a small key-value settings table and local JSON repositories are used for early-stage records. This keeps the current workflow explicit without prematurely locking in full business tables.

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
- `DISPENSE_DRY_RUN=true` as the default safety boundary.

Real mode failure must not break the dashboard. The backend returns a normal `/api/qsm/status` response with `connected=false`; the terminal UI only shows a user-facing device state such as “暂不可用”.

Stage six adds business-facing QSM action endpoints:

- `/api/qsm/vitals`: QSM gateway vitals read with mock/real fallback.
- `/api/qsm/camera/capture`: stable scan action endpoint backed by host-side camera service.
- `/api/qsm/dispense/dry-run`: local dry-run integration check.
- `/api/qsm/capabilities`: device capability summary for UI decisions.

The camera endpoint name is kept for UI compatibility, but it does not proxy to the gateway camera path in the current hardware split.

## Frontend layers

- `App.jsx`: top-level shell, current page state and toast feedback.
- `pages/`: Home, Medicines, Inquiry, Records and Scan pages.
- `components/`: terminal layout primitives and touch controls.
- `api/`: fetch client, dashboard API and mock fallback data.
- `styles/`: token-driven terminal styling.

The terminal is designed around a 1280x720 landscape canvas for an 11-inch touch display.

## Safety boundary

Through stage six, the system does not perform physical dispense. Drug access remains a dry-run confirmation workflow, and high-risk inquiry outcomes remain blocked from 取药确认.
