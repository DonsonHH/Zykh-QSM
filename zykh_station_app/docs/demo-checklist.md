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

For the first full QSM deployment, including the cabinet-light protocol module,
run:

```bash
sh scripts/deploy_qsm_gateway.sh
```

For an offline-TTS-only update, run:

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
- cabinet-light control from the live `STATUS` probe: “all off”, the exact cabinet still lit, or unavailable; do not accept configuration alone as ready;
- sync state.

5. Before any pickup test, verify the host status proxy reports all lights off:

```bash
curl http://127.0.0.1:8000/api/qsm/cabinet-light/status
```

The expected real-device result is `ok=true` and `status=off`. Do not continue
when the result is `unknown` or a cabinet is unexpectedly lit.

## Workflow Verification

1. Verify the homepage loads with today medication and emergency inquiry cards.
2. Verify the medicines page shows exactly three physical cabinet cards and all
   23 logical medicine items appear exactly once. Confirm that the original
   `hardware_slot=1..23` identities remain available through the API. The cards
   must be `日常用药 / 外用护理 / 慢病处方储备` with 9/8/6 items. Confirm S09
   双歧杆菌 is physically in cabinet 3 only after its current package storage
   instructions have been checked; if it requires refrigeration, stop this item
   and do not place it in an ordinary cabinet.
3. Verify the ordinary service-user list contains only `王奶奶` and `李爷爷`,
   and the four demo plans match their exact IDs, medicines, times and dose
   snapshots. Existing administrator edits must remain unchanged after restart.
4. Open the medicines page and tap “确认身份并点亮分类柜” once. The UI must
   automatically continue through identity → checking. A passed result must
   immediately continue to the correct cabinet light and the “还有药吗” page
   without a second confirmation; blocked, failed and guest results must keep
   the existing conflict/failure screen and say the cabinet light was not activated.
5. In a hardware-isolated run, verify `王奶奶 + S13 布洛芬` and
   `李爷爷 + S05 蜜炼川贝枇杷膏` both return
   `BLOCKED / CONDITION_CONTRAINDICATION`, create one safety event and call the
   fake QSM zero times.
6. Verify the inquiry page returns `source=cloud_responses` or
   `source=cloud_chat_fallback` while the cloud route is healthy.
7. Select local mode and verify inquiry still returns one of those cloud sources,
   the top bar shows local state, mini-program realtime sync pauses, and speech
   uses QSM offline TTS.
8. Verify all 23 fixed rows have the v7 controlled safety metadata; an expired,
   empty or unverified row may still be excluded after evaluation. Prescription
   attributes alone do not create a caregiver-approval state in the manual path.
9. In a controlled test session, verify a qualifying shallow-wound or adult
   watery-diarrhea case exposes only the exact authorized combination; revoking
   that combination before confirmation must return HTTP 409 without lighting
   another cabinet.
10. Verify the Scan page can show the QSM-camera capture state.
11. Select each person card on Records and verify its history drawer supports
    loading, empty, error, refresh and cursor pagination without showing messages,
    prompts or reasoning.
12. With a fake CloudBase adapter, verify safety events are append-only and
    idempotent, scoped caregivers can list/get/mark-read, and `OPEN_CABINET` is
    rejected in cloud, helper and Station layers with QSM call count zero.
13. Confirm the real serial path is ST-LINK VCP `/dev/ttyACM0` at 115200 8N1.
    `PING` must return exactly `PONG`; `STATUS` must return exactly `STATUS OFF`
    before the test. `/dev/ttyS5`, 9600 and single-byte `slot/control_code` are
    retired and must not be accepted as successful cabinet control.
14. Physical cabinet smoke requires `DISPENSE_DRY_RUN=false`,
    `ENABLE_REAL_DISPENSE=1` and request confirmation. Set the legacy-named
    `REAL_DISPENSE_TEST_SLOT` to physical cabinet ID `1`, `2` or `3` to limit the
    test. Verify exactly one expected panel lights and the other two stay off;
    the user must open the illuminated cabinet manually.
15. On “还有药吗”, choose the observed inventory state once. Verify its success
    message disappears, the UI automatically sends `OFF`, and
    `GET /api/qsm/cabinet-light/status` returns `status=off`; there must be no
    separate light-off click. Repeat the supervised observation for cabinets 1,
    2 and 3 only after the placement map is confirmed. A timeout or mismatched
    ACK must show `RESULT_UNKNOWN`; inspect the lights physically and do not press
    confirm again.

## Expected Degradation

- If the external gateway is unavailable in real mode, the UI should stay usable and show the gateway as not connected.
- If cabinet light state cannot be confirmed, the UI must not claim that a door opened; it should retain an explicit retry-safe `OFF` action or direct the operator to inspect the lights.
- If the QSM camera is unavailable in real mode, the Scan page should stay usable and allow manual verification.
- If recognition fails, the Scan page should request manual confirmation rather than filling a fake medicine.
- If the network is weak or unavailable, records remain local and can be shown as pending sync or not configured.
- If cloud AI is unavailable, inquiry must still return
  HTTP 200 with a natural retry prompt, emergency hard-guard behavior and no
  medicine candidate. The terminal UI must not display connection, model or
  fallback terminology.
- If QSM offline TTS is unavailable in local mode, the UI remains usable and reports a generic speech-unavailable state without exposing the internal engine.
