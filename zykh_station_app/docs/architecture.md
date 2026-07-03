# Architecture

## System boundary

`zykh_station_app` is the local master application. It owns the UI, station workflow, local persistence, rules fallback, inquiry records, dry-run records, and local sync simulation. QSM368ZP-WF remains an external peripheral gateway and is accessed only through the backend service boundary.

SQLite is initialized through a small key-value settings table and local JSON repositories are used for early-stage records. This keeps the current workflow explicit without prematurely locking in full business tables.

## Backend layers

- `main.py`: app factory, middleware, router registration and startup initialization.
- `routers/`: HTTP endpoints and request/response schemas.
- `services/`: station, dashboard, QSM gateway, inquiry, records and sync use cases.
- `repositories/`: SQLite persistence adapters.
- `schemas/`: Pydantic input/output contracts.
- `core/`: constants and safety language.

No route should call the peripheral gateway directly. Hardware-facing behavior goes through `services/qsm_client.py`.

## QSM gateway adapter

The gateway adapter supports:

- `QSM_MODE=mock`: stable local demo data.
- `QSM_MODE=real`: HTTP calls to `QSM_BASE_URL`, default `http://127.0.0.1:18080`.
- structured failure responses when the gateway is unavailable.
- `DISPENSE_DRY_RUN=true` as the default safety boundary.

Real mode failure must not break the dashboard. The backend returns a normal `/api/qsm/status` response with `connected=false`; the terminal UI only shows a user-facing device state such as “暂不可用”.

## Frontend layers

- `App.jsx`: top-level shell, current page state and toast feedback.
- `pages/`: Home, Medicines, Inquiry and Records pages.
- `components/`: terminal layout primitives and touch controls.
- `api/`: fetch client, dashboard API and mock fallback data.
- `styles/`: token-driven terminal styling.

The terminal is designed around a 1280x720 landscape canvas for an 11-inch touch display.

## Safety boundary

Through stage five, the system does not perform physical dispense. Drug access remains a dry-run confirmation workflow, and high-risk inquiry outcomes remain blocked from 取药确认.
