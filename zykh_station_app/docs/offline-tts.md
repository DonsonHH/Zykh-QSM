# 主机离线 TTS

离线语音合成现在由主机 FastAPI 进程负责。主机加载本地 Sherpa-ONNX 中文 VITS 模型，生成 PCM 后通过现有低延迟音频流发送到 QSM 喇叭。QSM 不再加载、启动或执行离线 TTS 模型，只保留本地 ASR、离线问询模型和 PCM 播放。

## 运行边界

- 主机：模型加载、文本转 PCM、语音任务串行化、播放时长管理。
- QSM：麦克风采集、离线 ASR、离线问询模型、PCM 播放和其他外设网关。
- 在线网络：仍可使用主机上的 Qwen 实时 TTS；生成的 PCM 同样发送到 QSM 喇叭。
- 设置页的本地显示模式不改变 TTS 路径；云端 TTS 不可用或调用方明确请求离线播报时，使用主机离线 TTS，且不调用 QSM `/api/audio/speak`。

旧的 QSM `local-tts-server` 部署已停用；新项目启动脚本不会再拉起或部署它。

## 主机部署

部署包只用于提取模型文件，不会上传到 QSM：

```bash
cd zykh_station_app
sh scripts/deploy_host_offline_tts.sh
```

默认模型目录为 `zykh_station_app/data/host_tts/`，该目录属于运行数据，不提交到 Git。也可以通过 `HOST_OFFLINE_TTS_MODEL_ROOT` 指定其他本机目录。

后端依赖包括：

```text
sherpa-onnx==1.13.4
numpy<2
```

启动后可以先预热模型，避免首次播报承担加载延迟：

```bash
curl -X POST http://127.0.0.1:8000/api/audio/host/warmup
curl http://127.0.0.1:8000/api/audio/status
```

## 配置

```text
HOST_OFFLINE_TTS_MODEL_ROOT=/path/to/zykh_station_app/data/host_tts
HOST_OFFLINE_TTS_THREADS=4
HOST_OFFLINE_TTS_TIMEOUT_SECONDS=45
HOST_OFFLINE_TTS_OUTPUT=qsm
```

`HOST_OFFLINE_TTS_OUTPUT` 支持：

- `qsm`：主机生成后发送到 QSM 喇叭；默认值。
- `auto`：优先发送到 QSM，QSM 播放通道不可用时使用主机声卡。
- `host`：只用主机声卡播放，适合没有 QSM 音频转发的开发机。

## 接口

`POST /api/audio/speak` 的 `mode=offline` 或本地网络模式会返回主机离线引擎，例如：

```json
{
  "ok": true,
  "requested_mode": "offline",
  "engine": "host-offline-sherpa-onnx",
  "offline": true,
  "raw": {
    "mode": "host-offline-sherpa-onnx-pcm",
    "sample_rate": 22050
  }
}
```

`GET /api/audio/host/status` 和 `GET /api/audio/status` 会显示模型文件、Python 运行时和播放路线是否就绪。模型或播放设备不可用时返回结构化错误，不返回假成功。

## 延迟说明

模型在后端进程中只加载一次，所有播报请求复用同一个已加载模型。`launch_kiosk.sh` 会在打开浏览器前同步调用 `/api/audio/host/warmup`；预热失败只给出警告，不阻断终端启动。每次播报只执行文本生成和 PCM 播放，不再重复加载 TTS 模型，也不再让 TTS 与 QSM 本地问询模型争抢内存。

当前主机实测中，预热约需 3.3 秒；预热后的短句首段音频生成约 0.8 秒。接口总耗时还包含实际语音播放时长，不能把正常播报时长误判为模型等待延迟。

在线 TTS 和主机离线 TTS 共用 QSM 的 PCM 播放端口 `19001`。启动前仍需执行 `scripts/adb_forward.sh`，但该脚本只建立 ASR、离线模型和音频播放端口，不会启动 QSM 离线 TTS。
