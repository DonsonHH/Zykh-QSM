# QSM 离线 TTS

语音播报由后端 `SpeechService` 统一串行调度，所有入口共享同一个播放锁，避免 HTTP 播报、小程序命令和后台任务同时抢占喇叭。

路由规则：

- 联网模式使用 Qwen 实时 TTS，将增量 PCM 送入 QSM 播放流；云端合成失败时安全回退到 QSM 离线 TTS；
- 本地模式直接调用 QSM `/api/audio/speak`，在板端使用 Sherpa-ONNX VITS 合成并播放；
- 模式只由持久化的终端演示状态解析，客户端提交的 `mode` 不能绕过该策略；
- 普通终端界面只显示正常播报状态，不展示云端/板端引擎名称。

## 部署

离线模型和运行库只部署到 QSM。主应用使用仓库内的 `qsm_gateway/offline_tts.sh`，不依赖历史 `zykh_app` 源码。

```bash
cd zykh_station_app
sh scripts/deploy_offline_tts.sh
```

部署脚本会：

1. 校验部署包、板端 `aarch64` 架构和唯一 ADB 设备；
2. 上传 Sherpa-ONNX 运行库、`zh_CN-xiao_ya-medium.onnx`、词典与规则 FST；
3. 上传本应用拥有的离线合成脚本及网关补丁；
4. 在板端执行一次不联网的 WAV 生成自检；
5. 启用 `/api/audio/speak` 路由并重启 QSM 网关。

默认目录：

```text
/userdata/zykh_voice/runtime
/userdata/zykh_voice/models/tts
/userdata/zykh_app/scripts/offline_tts.sh
```

`scripts/deploy_local_tts_server.sh` 作为兼容入口委托同一部署脚本。模型包和生成音频属于运行数据，不提交到 Git。

## 运行契约

板端每次请求调用受控的一次性合成脚本生成 WAV，由既有 QSM 音频路径播放。网关补丁会迁移旧的 `HOST_TTS_ONLY` 块，并保证重复执行幂等。后端状态接口从 QSM 返回离线模型可用性，不再把主机模型状态当作本地语音就绪条件。

应用启动默认关闭旧 QSM llama.cpp 语言模型，为 TTS、ASR 和外设服务释放内存。停止脚本只会终止 PID 文件指向且命令行同时匹配预期 server 与模型的进程，不使用宽泛 `pkill`。

## 验收

部署后至少验证：

```bash
curl http://127.0.0.1:8000/api/audio/status
curl -X POST http://127.0.0.1:8000/api/audio/speak \
  -H 'Content-Type: application/json' \
  -d '{"text":"智药康护语音测试。"}'
```

自动测试必须 mock QSM 和云端 TTS；真实板端播放只在明确的人工 smoke 阶段执行。
