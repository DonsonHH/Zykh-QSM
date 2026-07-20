# Offline ASR

The local speech-to-text route uses the user-supplied
`QSM368ZP-offline-asr-migration` bundle. It replaces the previous streaming
Zipformer module with `sherpa-onnx` Paraformer zh-small int8.

## Runtime flow

```text
QSM FF Camera microphone (S16_LE, 16 kHz, mono)
  -> host /api/audio/asr/realtime control channel
  -> buffer until the user presses stop
  -> float PCM request
  -> QSM resident Paraformer on port 6006
  -> one final transcript
```

The host keeps port `18084` for compatibility. `adb forward` maps it to QSM
port `6006`. The model is loaded once at gateway startup. The supplied board
report measured roughly 0.86-0.98 seconds of recognition for a five-second
utterance after warm-up; microphone recording time is additional.

## Deploy

Place `QSM368ZP-offline-asr-migration*.zip` at the repository root, or provide
an explicit path:

```bash
cd zykh_station_app
ASR_BUNDLE_ZIP=/path/to/QSM368ZP-offline-asr-migration.zip \
  sh scripts/deploy_local_asr.sh
```

The script:

1. verifies the ARM64 board and SHA-256 hashes of the model and runtime;
2. stops and removes `/userdata/zykh_app/local_asr`, the old Zipformer module;
3. installs the ASR runtime under `/userdata/zykh_voice`; offline TTS is now
   hosted on the main application machine and does not use this board runtime;
4. installs and starts `/userdata/zykh_app/scripts/start_asr_service.sh`;
5. updates the board compatibility API and startup hooks;
6. recognizes the bundle's `penicillin-allergy.wav` on the real QSM board.

The deployment bundle is intentionally not committed to Git because it is
about 125 MB. It contains its own Apache 2.0 license and third-party notices.

## Verify

```bash
adb shell /userdata/zykh_app/scripts/start_asr_service.sh status
adb forward tcp:18084 tcp:6006
curl http://127.0.0.1:8000/api/audio/status
curl -X POST http://127.0.0.1:8000/api/audio/asr \
  -H 'Content-Type: application/json' \
  -d '{"duration":6}'
```

The board endpoint returns `offline=true` and model
`paraformer-zh-small-2024-03-09-int8-resident`. Online mode continues to use
Qwen realtime ASR; changing network mode to local selects this offline route.
