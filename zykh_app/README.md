# QSM compatibility gateway

`zykh_app/` is the retained compatibility layer for the QSM Buildroot board. It is not the terminal UI and must not be imported by `zykh_station_app`.

The active host application is [`../zykh_station_app/`](../zykh_station_app/), which contains the React kiosk, FastAPI backend, SQLite repositories and deployable QSM device gateways.

## Retained files

- `server.pl`: legacy board HTTP gateway still used for status, cabinet control, network and audio compatibility endpoints.
- `scripts/start_zykh_server.sh`: board gateway launcher.
- `scripts/offline_tts.sh`: offline TTS adapter used by `zykh_station_app/scripts/deploy_offline_tts.sh`.
- `scripts/play_beep.sh`: speaker compatibility test.
- `scripts/read_gy614_uart4.pl` and `scripts/read_max30102_vitals.pl`: legacy sensor fallbacks.
- `tools/` and `bin/zykh-ai-voice`, `bin/zykh-scan-code`: reproducible helper sources and board binaries required by compatibility APIs.

The old Go framebuffer UI, static HTML terminal, bundled display font, Weston helpers and old Wi-Fi watchdog were removed. The host kiosk now owns all user-facing pages.

## Deployment

Use the scripts in `zykh_station_app/scripts/`. They deploy the required board gateways to stable `/userdata/zykh_app` and `/userdata/qsm-*` paths without making the host application depend on this directory.

Check the compatibility gateway before deployment:

```bash
perl -c zykh_app/server.pl
```

Do not commit API keys or board runtime data. Keys belong in local environment variables or ignored files under `/userdata/zykh_app/data/`.
