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

For the first QSM offline-TTS deployment, run:

```bash
sh scripts/deploy_offline_tts.sh
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
- QSM local-voice readiness;
- cabinet control: real linkage or temporarily disabled, matching the environment;
- sync state.

## Workflow Verification

1. Verify the homepage loads with today medication and emergency inquiry cards.
2. Verify the medicines page loads inventory.
3. Verify the ordinary service-user list contains only `王奶奶` and `李爷爷`,
   and the four demo plans match their exact IDs, medicines, times and dose
   snapshots. Existing administrator edits must remain unchanged after restart.
4. Open the medicines page and verify the manual path is identity → checking →
   passed/blocked/check-failed. A passed result still requires the explicit
   “确认取药并开柜” action; blocked, failed and guest results must say the cabinet
   was not opened.
5. In a hardware-isolated run, verify `王奶奶 + S13 布洛芬` and
   `李爷爷 + S05 蜜炼川贝枇杷膏` both return
   `BLOCKED / CONDITION_CONTRAINDICATION`, create one safety event and call the
   fake QSM zero times.
6. Verify the inquiry page returns `source=cloud_responses` or
   `source=cloud_chat_fallback` while the cloud route is healthy.
7. Select local mode and verify inquiry still returns one of those cloud sources,
   the top bar shows local state, mini-program realtime sync pauses, and speech
   uses QSM offline TTS.
8. Verify all 23 fixed rows have the v5 controlled safety metadata; an expired,
   empty or unverified row may still be excluded after evaluation. Prescription
   attributes alone do not create a caregiver-approval state in the manual path.
9. In a controlled test session, verify a qualifying shallow-wound or adult
   watery-diarrhea case exposes only the exact authorized combination; revoking
   that combination before confirmation must return HTTP 409 without opening
   another cabinet.
10. Verify the Scan page can show the QSM-camera capture state.
11. Select each person card on Records and verify its history drawer supports
    loading, empty, error, refresh and cursor pagination without showing messages,
    prompts or reasoning.
12. With a fake CloudBase adapter, verify safety events are append-only and
    idempotent, scoped caregivers can list/get/mark-read, and `OPEN_CABINET` is
    rejected in cloud, helper and Station layers with QSM call count zero.
13. Physical cabinet smoke requires `DISPENSE_DRY_RUN=false`,
    `ENABLE_REAL_DISPENSE=1` and request confirmation. Set
    `REAL_DISPENSE_TEST_SLOT` when you need to restrict testing to one slot. A
    timeout must show `RESULT_UNKNOWN`; do not press confirm again.

## Expected Degradation

- If the external gateway is unavailable in real mode, the UI should stay usable and show the gateway as not connected.
- If the QSM camera is unavailable in real mode, the Scan page should stay usable and allow manual verification.
- If recognition fails, the Scan page should request manual confirmation rather than filling a fake medicine.
- If the network is weak or unavailable, records remain local and can be shown as pending sync or not configured.
- If cloud AI is unavailable, inquiry must still return
  HTTP 200 with a natural retry prompt, emergency hard-guard behavior and no
  medicine candidate. The terminal UI must not display connection, model or
  fallback terminology.
- If QSM offline TTS is unavailable in local mode, the UI remains usable and reports a generic speech-unavailable state without exposing the internal engine.
