# QSM Real Connection Audit

> This file records the earlier main-gateway audit. The current offline inquiry model is a separate llama.cpp service on QSM port `8083`, forwarded to host port `18083`; see `offline-ai.md`.

> Historical audit snapshot. It records the previous dry-run safety baseline at the time of that check. Current runtime defaults are real-device first: `QSM_MODE=real`, `LOCAL_CAMERA_MODE=real`, `DISPENSE_DRY_RUN=false`, `ENABLE_REAL_DISPENSE=1`.

## Overall Verdict

- QSM gateway deployed: yes
- QSM gateway running: yes, after restart
- adb forward working: yes, `tcp:18080 -> tcp:8080`
- zykh_station_app connected to QSM: yes
- AI cloud channel working: fallback from station app; QSM-side cloud call failed on DNS during audit
- camera working: local camera working; QSM camera capture unavailable; QSM camera frame endpoint has cached JPG output
- vitals working: yes, QSM `read_all` and station `/api/vitals/read-all` returned available
- dispense tested: dry-run only

## Evidence

Commands run with sensitive values redacted:

```bash
adb devices -l
# ? device usb:1-2.1 product:rk3568-linux model:Nexus_4 device:mako transport_id:1

adb shell "ls -la /userdata/zykh_app/server.pl || true"
# /userdata/zykh_app/server.pl exists

adb shell "perl -c /userdata/zykh_app/server.pl 2>&1 || true"
# /userdata/zykh_app/server.pl syntax OK

adb shell "wget -qO- http://127.0.0.1:8080/api/status 2>&1 || true"
# initially: connection refused

adb shell "cd /userdata/zykh_app && perl server.pl --daemon; sleep 1; pidof perl"
# started pid 3547, later restarted as pid 4682

adb shell "wget -qO- http://127.0.0.1:8080/api/status 2>&1 | head -c 160"
# {"arch":"aarch64","time":"2006-09-20 ...","os":"Buildroot 2018.02-rc3", ...}

adb forward tcp:18080 tcp:8080
curl http://127.0.0.1:18080/api/status
# HTTP 200, QSM status JSON
```

Station app smoke after fixes:

```text
GET  /api/health -> 200 dry_run=true enable_real_dispense=false real_dispense_enabled=false
GET  /api/qsm/status -> 200 connected=true
GET  /api/device/check -> 200 qsm_connected=true dispense_dry_run=true
GET  /api/qsm/capabilities -> 200 qsm_connected=true
GET  /api/qsm/vitals -> 200 status=available or awaiting_finger
POST /api/qsm/dispense/dry-run -> 200 dry_run=true
```

Direct QSM route checks:

```text
POST /api/vitals/read -> 200 ok=true, source=UART8-vitals-24B, quality=no_finger or stable
POST /api/vitals/read_all -> 200 ok=true, UART8-vitals-24B + GY-614
POST /api/vitals/temp/read -> 200 ok=true, source=GY-614
POST /api/camera/capture -> 200 ok=false, camera hardware pipeline unavailable
GET  /api/camera/frame -> 200 cached JPEG bytes returned
POST /api/audio/beep -> 200 ok=true
POST /api/audio/speak -> timeout
POST /api/audio/asr -> timeout
POST /api/ai/chat -> 200 ok=false, DNS temporary failure
```

## QSM Route Map

| Function | Actual QSM interface | Method | Params | Accessible | Notes |
|---|---|---:|---|---|---|
| status | `/api/status` | GET | none | yes | Returns Buildroot, devices, time |
| vitals history | `/api/vitals` | GET/POST | sensor fields | not smoke-tested | Present in `server.pl` |
| UART8 integrated vitals | `/api/vitals/read` | POST | none | yes | 24-byte frames received; no-finger and measured states verified |
| temperature GY-614 | `/api/vitals/temp/read` | POST | none | yes | Returned body temperature |
| vitals all | `/api/vitals/read_all` | POST | none | yes | Combined UART8 integrated sensor + GY-614 |
| camera capture | `/api/camera/capture` | POST | none | partial | Route works; hardware pipeline returned unavailable |
| camera frame | `/api/camera/frame` | GET | none | partial | Returned cached JPEG |
| camera stream | `/api/camera/stream` | GET | width/fps query | not smoke-tested | Present in `server.pl` |
| camera stop | `/api/camera/stream/stop` | POST | none | not smoke-tested | Present in `server.pl` |
| audio beep | `/api/audio/beep` | POST | optional volume | yes | Played through QSM script |
| audio speak | `/api/audio/speak` | POST | `text` | no | Timed out in audit |
| audio ASR | `/api/audio/asr` | POST | `duration` | no | Timed out in audit |
| AI chat | `/api/ai/chat` | POST | JSON/form message | no | DNS failure from QSM |
| dispense | `/api/dispense` | POST | `slot` | not tested | Not called; physical dispense disabled |

## zykh_station_app Mapping

| Station config | Current value |
|---|---|
| `QSM_MODE` | `real` |
| `QSM_BASE_URL` | `http://127.0.0.1:18080` |
| `QSM_STATUS_PATH` | `/api/status` |
| `QSM_VITALS_PATH` | `/api/vitals/read` |
| `QSM_VITALS_ALL_PATH` | `/api/vitals/read_all` |
| `QSM_TEMP_PATH` | `/api/vitals/temp/read` |
| `QSM_CAMERA_CAPTURE_PATH` | `/api/camera/capture` |
| `QSM_CAMERA_STREAM_PATH` | `/api/camera/stream` |
| `QSM_AUDIO_SPEAK_PATH` | `/api/audio/speak` |
| `QSM_AUDIO_ASR_PATH` | `/api/audio/asr` |
| `QSM_AUDIO_BEEP_PATH` | `/api/audio/beep` |
| `QSM_AI_CHAT_PATH` | `/api/ai/chat` |
| `LOCAL_AI_BASE_URL` | `http://127.0.0.1:18083` |
| `QSM_DISPENSE_PATH` | `/api/dispense` |

## Problems Found

- QSM gateway existed but was not running at the start; port 8080 returned connection refused.
- QSM board time is still around year 2006, which can break TLS certificate validation.
- QSM-side AI chat failed with DNS temporary failure.
- Station AI key was not configured in env, `.env.local`, or `/userdata/zykh_app/data/ai-api-key.txt`; `previous_work.md` contains a historical key reference but it was not copied.
- QSM camera capture route returned a camera pipeline error; host-side local camera remains the working camera path.
- QSM audio speak and ASR timed out and can block the single Perl gateway process long enough to require restart.
- Historical note: at the time of this audit, cabinet action was kept non-physical while safety gates were being verified. Current defaults are documented in README and qsm-integration.md.

## Fixes Applied

- `backend/app/config.py`: added `.env.local` loading, QSM stream/AI paths, longer QSM timeout, `ENABLE_REAL_DISPENSE`, and `real_dispense_enabled()`.
- `backend/app/services/qsm_client.py`: status no longer triggers expensive vitals reads; POST supports form and JSON body formats; empty gateway responses become structured errors; vitals parsing preserves zero values.
- `backend/app/services/dispense_service.py`: real dispense now requires dry-run off, enable flag on, matching safe slot, and request confirmation.
- `backend/app/schemas/dispense.py`: added `confirm_real_dispense`.
- `backend/app/routers/health.py`, `backend/app/routers/qsm.py`, `backend/app/services/device_check_service.py`, `backend/app/services/dashboard_service.py`: aligned status with the new safety gate.
- `.gitignore`: added `backend/.env.local`.
- README and QSM docs updated to document the safe defaults.

## Secrets Handling

- key found: true
- key source: previous_work
- key redacted: `sk-****ea76`
- key printed: no
- key submitted to Git: no
- key written to `.env.local`: no
- `.env.local` gitignored: yes

## Next Actions

P0:

- Keep QSM gateway running before station app smoke: `cd /userdata/zykh_app && perl server.pl --daemon`.
- Fix QSM board time before cloud/TLS checks.
- Configure AI key in `zykh_station_app/backend/.env.local` or `/userdata/zykh_app/data/ai-api-key.txt`.
- Confirm a safe empty slot before any real dispense test.

P1:

- Stabilize QSM camera capture path or keep host-side camera as the primary capture path.
- Diagnose QSM audio speak/ASR timeout and avoid blocking the Perl gateway.
- Re-test QSM AI chat after DNS/network and time are fixed.

P2:

- Add a QSM gateway watchdog/start script.
- Add a targeted station smoke script that skips physical dispense unless the double safety gate is present.
