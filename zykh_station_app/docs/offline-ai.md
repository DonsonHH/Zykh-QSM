# QSM Offline AI

## Purpose

The terminal uses a real offline language model for AI inquiry when the cloud
route is unavailable or the operator selects local mode. The model runs on QSM;
FastAPI calls it through an ADB-forwarded OpenAI-compatible endpoint. The model
owns open case understanding, natural follow-up and semantic risk judgment.
Deterministic code retains only non-negotiable danger interception and medicine
safety constraints.

```text
React inquiry UI
  -> FastAPI AiService
     -> cloud Chat Completions when reachable
     -> QSM llama.cpp when cloud is unavailable
     -> natural retry prompt with no candidate when both model routes fail
```

## Runtime

Verified deployment:

- engine: `llama.cpp` `llama-server`, AArch64 build from the supplied example bundle;
- model repository: [unsloth/Qwen3.5-0.8B-GGUF](https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF);
- model file: `Qwen3.5-0.8B-Q4_K_M.gguf`;
- model size: `532517120` bytes;
- model SHA-256: `bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517`;
- engine SHA-256: `683752e7bb06850a1ebed20d001203549dc588b234b89c5ba264da573d17a9d0`;
- QSM endpoint: board `8083`, forwarded to host `127.0.0.1:18083`;
- model assets: `/opt/zykh-local-ai`;
- PID, logs and control scripts: `/userdata/zykh_station_app/local-ai`.

The upstream base model is [Qwen/Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B). Review the upstream model card and license before redistribution.

## Download And Deploy

Keep the supplied example ZIP at the repository root, or set `OFFLINE_AI_EXAMPLE_ARCHIVE`. The ZIP is used only to obtain the verified AArch64 `llama-server`; it is not imported into the application.

```bash
cd zykh_station_app
sh scripts/download_offline_model.sh
sh scripts/deploy_offline_ai.sh
```

The download is resumable and verifies both exact size and SHA-256. The deploy script:

1. checks ADB and QSM architecture;
2. validates engine and model hashes;
3. temporarily remounts the QSM root filesystem read/write only when model assets must change;
4. restores the root filesystem read-only through normal completion and signal traps;
5. installs lifecycle scripts under `/userdata`;
6. establishes `tcp:18083 -> tcp:8083`;
7. starts the model and runs health plus real inference smoke checks.

`launch_kiosk.sh` calls `ensure_qsm_offline_ai.sh` by default. Disable that startup check only for troubleshooting:

```bash
KIOSK_OFFLINE_AI=0 sh scripts/launch_kiosk.sh
```

## Lifecycle

Host-side check/start:

```bash
sh scripts/ensure_qsm_offline_ai.sh
curl http://127.0.0.1:18083/health
```

Board-side lifecycle:

```bash
adb shell 'sh /userdata/zykh_station_app/local-ai/status_local_ai.sh'
adb shell 'sh /userdata/zykh_station_app/local-ai/stop_local_ai.sh'
adb shell 'sh /userdata/zykh_station_app/local-ai/start_local_ai.sh'
```

## Application Configuration

```text
AI_MODE=auto
AI_CONNECTIVITY_TIMEOUT_SECONDS=2
LOCAL_AI_BASE_URL=http://127.0.0.1:18083
LOCAL_AI_CHAT_PATH=/v1/chat/completions
LOCAL_AI_HEALTH_PATH=/health
LOCAL_AI_MODEL=Qwen3.5-0.8B-Q4_K_M
LOCAL_AI_TIMEOUT_SECONDS=45
LOCAL_AI_HEALTH_TIMEOUT_SECONDS=2
LOCAL_AI_CTX_SIZE=1536
LOCAL_AI_THREADS=4
LOCAL_AI_BATCH_SIZE=256
LOCAL_AI_UBATCH_SIZE=64
LOCAL_AI_CACHE_RAM=64
```

板端默认只保留最近 6 条有效对话，并以 `1024` 上下文、较小批次运行。这个配置用于控制
2GB 内存设备上的峰值占用，避免体征、身份识别或离线语音合成同时工作时系统终止
`llama-server`。如更换内存更大的板卡，可通过上述环境变量单独放大。

Modes:

- `AI_MODE=auto`: cloud first; use QSM offline model on missing key, failed connectivity or cloud request error.
- `AI_MODE=local`: always use the QSM offline model.
- `AI_MODE=cloud`: request cloud first, but still fail safely to the offline model if the request cannot complete.

Inquiry-session source values remain internal diagnostics. The terminal UI uses
accessible icons and natural retry guidance instead of exposing channel names,
connection errors or “rules fallback” wording. Legacy stored sessions containing
those technical phrases are normalized when read; the original SQLite history
is not rewritten.

## Safety Boundary

Before and after inference, the backend enforces only hard boundaries:

- deterministic emergency keyword interception;
- negation-aware handling such as “没有胸痛”;
- no direct medication instruction or diagnostic claim;
- program risk may raise but never lower the model risk;
- stock, expiry, OTC eligibility and absolute-contraindication filtering before ranking;
- model selection restricted to IDs in that filtered pool;
- current-state revalidation before the existing dispense service runs;
- zero candidates when both model routes fail;
- emergency hard guards remain available even when neither model responds.

## Verified Performance

On the connected RK3568 QSM with 2 GB RAM, the deployed model passed real Chinese inquiry requests. The observed run was approximately 24.7 prompt tokens/s and 6.1 generated tokens/s. A warm compact case turn normally completes in roughly 10–15 seconds. For a large medicine pool, the model first chooses up to two relevant medicine categories and then ranks only the medicines in those categories; the complete two-pass selection observed roughly 20–30 seconds instead of timing out on an 18-medicine, 1536-token request. The host applies the safety pool before both calls and accepts only exact category and medicine names from that pool. With the language model and resident ASR loaded together, the board keeps the TTS model off-device, leaving more memory and CPU headroom; these timings are deployment observations, not hard guarantees.

## Offline Verification

```bash
curl http://127.0.0.1:8000/api/ai/status
curl -X POST http://127.0.0.1:8000/api/network/mode \
  -H 'Content-Type: application/json' \
  -d '{"mode":"local"}'
curl -X POST http://127.0.0.1:8000/api/ai/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"我有轻微头晕，请先问一个关键问题"}]}'
```

Expected session source is `local_llm`. To verify failure handling, stop the
local model and repeat an `/api/inquiry/sessions/{id}/turn` request; the endpoint
must stay available, return a natural retry prompt, and return no medicine
candidate rather than HTTP 500 or terminal-facing transport details.
