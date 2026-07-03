# QSM Integration

## First-stage mode

The first stage defaults to:

```text
QSM_MODE=mock
DISPENSE_DRY_RUN=true
```

This lets the new local app run without requiring peripheral hardware to be connected.

## Real mode seam

When real mode is enabled, the backend calls:

```text
http://127.0.0.1:18080
```

The only module allowed to know about this URL is `backend/app/services/qsm_client.py`.

First-stage supported client methods:

- `health_check()`
- `get_qsm_status()`
- `read_vitals()`
- `get_device_status()`

Camera capture, physical dispense, voice playback and sensor-specific troubleshooting are intentionally deferred to later stages.
