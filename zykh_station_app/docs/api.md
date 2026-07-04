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
- host camera readiness;
- dispense safety flag;
- errors, warnings and recommendations.

The endpoint always returns HTTP 200 for expected missing-device cases so the terminal UI can degrade gracefully.

### GET /api/medicines

Returns the home cabinet medicine list and available categories.

### GET /api/medicines/{medicine_id}

Returns a single medicine detail.

### POST /api/dispense/confirm

Requires the safety notice confirmation flag and writes a local 取药确认 record. By default it calls the QSM dispense path when `DISPENSE_DRY_RUN=false`, `ENABLE_REAL_DISPENSE=1`, and request body `confirm_real_dispense=true`. `REAL_DISPENSE_TEST_SLOT` is optional; when configured, only the matching slot can open.

### GET /api/dispense/records

Returns local dispense confirmation records.

### POST /api/inquiry/evaluate

Runs rules fallback for AI应急问询, risk prompts, medicine category matching and contraindication checks.

### GET /api/inquiry/{inquiry_id}

Returns one inquiry result.

### GET /api/inquiry/records

Returns recent inquiry results.

### GET /api/records/summary

Returns local SQLite record counters for the records page.

### GET /api/records/recent

Returns a compact list of recent local service records, including inquiry, dispense, vitals and scan records.

### GET /api/sync/status

Returns local sync state. If no cloud sync endpoint is configured, the state is `未配置` with pending local records.

### POST /api/sync/run

Attempts a configured cloud sync. If no endpoint is configured, it returns HTTP 200 with a `未配置` message and does not mark records as synced.

### GET /api/qsm/vitals

Reads vitals through the QSM adapter and stores successful/failed readings locally. Real mode tries all configured vitals paths and returns HTTP 200 with `status=unavailable` when the peripheral gateway is unreachable.

### POST /api/qsm/camera/capture

Compatibility endpoint for the Scan page. With the latest hardware split, the backend uses the host-side camera seam rather than the peripheral gateway camera path. Real capture failures return the actual command/device error and do not create fake medicine results.

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

### POST /api/vitals/read-all

Reads all available vitals through QSM. It prefers `QSM_VITALS_ALL_PATH`, then falls back to `QSM_VITALS_PATH` and `QSM_TEMP_PATH`.

### POST /api/camera/capture

Captures one image from the host-side camera using `LOCAL_CAMERA_DEVICE`. The response includes image availability, image path when available and a structured error on failure.

### POST /api/medicine/scan

Captures an image, tries local barcode decoding, then Qwen visual recognition when configured. If both fail, it returns `manual_required` instead of a fake match.

### POST /api/medicine/visual-recognize

Runs the visual recognition fallback against an existing image path.

### POST /api/audio/asr

Calls the QSM audio ASR path and returns recognized text or a structured gateway error.

### POST /api/audio/speak

Calls the QSM speech path with text.

### POST /api/audio/beep

Calls the QSM beep path.

### POST /api/ai/chat

Calls the configured DeepSeek-compatible cloud endpoint when a key is available. Without a key or network, it returns a local rules fallback response with `source=local_fallback`.

### POST /api/ai/chat/stream

Streams the same AI response as server-sent events.
