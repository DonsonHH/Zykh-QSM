# Device Acceptance Checklist

Use this checklist before live hardware acceptance or a public run-through.

## Device And App Startup

1. Start the existing peripheral gateway service on the QSM board.
2. Connect the QSM board to the host machine.
3. Run the forwarding helper:

```bash
cd zykh_station_app
sh scripts/adb_forward.sh
```

For the first offline-model deployment, run `sh scripts/deploy_offline_ai.sh`. On later starts, verify or start it with:

```bash
sh scripts/ensure_qsm_offline_ai.sh
```

4. Start the backend:

```bash
QSM_MODE=real QSM_BASE_URL=http://127.0.0.1:18080 DISPENSE_DRY_RUN=false ENABLE_REAL_DISPENSE=1 sh scripts/start_backend.sh
```

5. Start the frontend:

```bash
sh scripts/start_frontend.sh
```

6. Open the terminal page:

```text
http://127.0.0.1:5173
```

7. For kiosk display:

```bash
sh scripts/open_kiosk.sh
```

## Readiness Checks

1. Run the script check:

```bash
sh scripts/check_devices.sh
```

2. Check the backend readiness API:

```bash
curl http://127.0.0.1:8000/api/device/check
```

3. Open the terminal UI and tap the system-check button in the top-right area.
4. Confirm the page shows:

- current mode: mock or real;
- external gateway connection state;
- QSM camera state;
- vitals module state;
- QSM offline model state and model name;
- cabinet control: real linkage or temporarily disabled, matching the environment;
- sync state.

## Workflow Verification

1. Verify the homepage loads with today medication and emergency inquiry cards.
2. Verify the medicines page loads inventory.
3. Open the medicines page and inspect the 取药确认 modal. Submit physical cabinet open only when the selected slot is safe to test.
4. Verify the inquiry page returns `source=cloud` while the cloud route is healthy.
5. Select local mode and verify `/api/ai/chat` returns `source=local_llm` from QSM.
6. Verify the Scan page can show the QSM-camera capture state.
7. Verify the records page shows local records and pending sync state.
8. Physical cabinet smoke requires `DISPENSE_DRY_RUN=false`, `ENABLE_REAL_DISPENSE=1` and request confirmation. Set `REAL_DISPENSE_TEST_SLOT` when you need to restrict testing to one slot.

## Expected Degradation

- If the external gateway is unavailable in real mode, the UI should stay usable and show the gateway as not connected.
- If the QSM camera is unavailable in real mode, the Scan page should stay usable and allow manual verification.
- If recognition fails, the Scan page should request manual confirmation rather than filling a fake medicine.
- If the network is weak or unavailable, records remain local and can be shown as pending sync or not configured.
- If cloud AI is unavailable, inquiry should use the QSM offline model and report `source=local_llm`.
- If both cloud and QSM offline model are unavailable, inquiry must still return
  HTTP 200 with a natural retry prompt, emergency hard-guard behavior and no
  medicine candidate. The terminal UI must not display connection, model or
  fallback terminology.
