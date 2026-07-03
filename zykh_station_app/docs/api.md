# API

Base URL during development:

```text
http://127.0.0.1:8000
```

## Endpoints

### GET /api/health

Returns service, database, QSM mode and dry-run status.

### GET /api/status

Returns top-level station status for the terminal shell:

- network mode;
- AI mode;
- peripheral device status;
- sync status;
- dry-run flag;
- status chips.

### GET /api/site

Returns the station profile displayed by the terminal.

### POST /api/site

Updates the station profile fields used by the terminal.

### GET /api/dashboard

Returns fixed first-stage homepage data:

- site profile;
- top status chips;
- today medication summary;
- emergency inquiry summary;
- quick actions;
- bottom station stats;
- safety notice.

### GET /api/qsm/status

Returns mock or real peripheral gateway status. Defaults to mock mode.

### GET /api/device/check

Returns the demonstration readiness check:

- QSM mode and connection state;
- QSM base URL;
- QSM status and vitals readiness;
- host camera readiness;
- dry-run safety flag;
- errors, warnings and recommendations.

The endpoint always returns HTTP 200 for expected missing-device cases so the terminal UI can degrade gracefully.

### GET /api/medicines

Returns the station medicine list and available categories.

### GET /api/medicines/{medicine_id}

Returns a single medicine detail.

### POST /api/dispense/confirm

Writes a local 取药确认 dry-run record. Requires the safety notice confirmation flag. It never triggers physical dispense while `DISPENSE_DRY_RUN=true`.

### GET /api/dispense/records

Returns local dry-run records.

### POST /api/inquiry/evaluate

Runs rules fallback for AI应急问询, risk prompts, medicine category matching and contraindication checks.

### GET /api/inquiry/{inquiry_id}

Returns one inquiry result.

### GET /api/inquiry/records

Returns recent inquiry results.

### GET /api/records/summary

Returns local record counters for the records page.

### GET /api/records/recent

Returns a compact list of recent local service records, including inquiry, dry-run, vitals and scan records.

### GET /api/sync/status

Returns local mock sync state.

### POST /api/sync/mock

Marks the local mock sync queue as synced. It does not call a real cloud service.

### GET /api/qsm/vitals

Reads vitals through the QSM adapter. Mock mode returns:

- `temperature: 35.7`
- `heart_rate: null`
- `spo2: null`
- `status: partial`

Real mode returns HTTP 200 with `status=unavailable` when the peripheral gateway is unreachable.

### POST /api/qsm/camera/capture

Runs the scan/capture action used by the Scan page. With the latest hardware split, the backend uses the host-side camera seam rather than the peripheral gateway camera path. Mock mode returns a sample medicine recognition result.

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
