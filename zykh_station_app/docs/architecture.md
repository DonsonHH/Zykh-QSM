# Architecture

## First-stage boundary

`zykh_station_app` is the new local master application. It owns the UI, station workflow, local persistence, AI routing seams, and local sync simulation. QSM368ZP-WF remains an external peripheral gateway and is accessed only through the new backend service boundary.

The first stage intentionally avoids a full business model. SQLite is initialized through a small key-value settings table so the app has a real persistence seam without locking in premature domain tables.

## Backend layers

- `main.py`: app factory, middleware, router registration and startup initialization.
- `routers/`: HTTP endpoints and request/response schemas.
- `services/`: station, dashboard and QSM gateway use cases.
- `repositories/`: SQLite persistence adapters.
- `schemas/`: Pydantic input/output contracts.
- `core/`: constants and safety language.

No route should call the peripheral gateway directly. Hardware-facing behavior goes through `services/qsm_client.py`.

## Frontend layers

- `App.jsx`: top-level shell, current page state and toast feedback.
- `pages/`: first-stage Home page and future-page placeholder.
- `components/`: terminal layout primitives and touch controls.
- `api/`: fetch client, dashboard API and mock fallback data.
- `styles/`: token-driven terminal styling.

The terminal is designed around a 1280x720 landscape canvas for an 11-inch touch display.
