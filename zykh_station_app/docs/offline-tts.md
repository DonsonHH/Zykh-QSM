# QSM offline TTS

## Purpose

The QSM gateway can synthesize Chinese speech without Wi-Fi, SIM connectivity or an API key. It uses the aarch64 `sherpa-onnx` runtime and the INT8 `zh_CN-xiao_ya-medium` VITS model supplied in the local deployment archive. A persistent service keeps the model loaded and streams generated PCM to `aplay`; the original per-request WAV script remains a compatibility fallback.

The model and runtime are deployed to QSM but are not committed to Git:

```text
/userdata/zykh_voice/runtime/
/userdata/zykh_voice/models/tts/
/userdata/zykh_app/scripts/offline_tts.sh
/userdata/zykh_app/bin/local-tts-server
/userdata/zykh_app/scripts/start_local_tts_server.sh
```

## Routing

`POST /api/audio/speak` supports three QSM request modes:

- `offline`: only the board-side model is allowed; no cloud TTS request is made.
- `auto`: cloud TTS is attempted first, then the board-side model if cloud synthesis fails.
- `cloud`: cloud TTS is preferred, with the board-side model retained as the safety fallback.

The host FastAPI service selects `offline` whenever the configured or detected network mode is local. It selects `auto` while Wi-Fi or SIM networking is available. Responses include the actual engine (`qwen-tts` or `offline-sherpa-onnx`) and an `offline` flag.

## Deployment

Place `智药康护-QSM368ZP离线TTS部署包(1).zip` in the repository root, connect exactly one QSM through ADB, then run:

```bash
cd zykh_station_app
INSTALL_GATEWAY=1 PLAYBACK_TEST=1 sh scripts/deploy_offline_tts.sh
```

The script checks aarch64 compatibility and free space, uploads the runtime and model, verifies key SHA-256 hashes, backs up and installs the current gateway when requested, generates a Chinese WAV entirely on QSM, and optionally plays it through the QSM speaker. Then deploy the persistent streamer:

```bash
sh scripts/deploy_local_tts_server.sh
```

## Verification

```bash
sh scripts/adb_forward.sh
curl http://127.0.0.1:8000/api/audio/status
curl -X POST http://127.0.0.1:8000/api/audio/speak \
  -H 'Content-Type: application/json' \
  -d '{"text":"离线语音播报测试成功。","mode":"offline","speed":1.2}'
```

A successful offline response contains:

```json
{
  "ok": true,
  "requested_mode": "offline",
  "engine": "offline-sherpa-onnx",
  "offline": true
}
```

On the verified board, the old process-per-request route took about 17.18 seconds for a short sentence because model loading consumed roughly 14 seconds. Keeping the model resident reduced end-to-end time to about 4.16 seconds and began playback after about 1.28 seconds. This is still the offline fallback; online speech uses Qwen realtime TTS and writes each PCM delta directly to QSM. The bundled voice model is restricted to non-commercial use; replace it or obtain suitable licensing before commercial distribution.

Offline speech recognition is deployed separately from TTS. See
[`offline-asr.md`](offline-asr.md) for the resident Paraformer service,
deployment bundle, ports and real-board verification.
