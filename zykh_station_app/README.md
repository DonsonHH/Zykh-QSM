# zykh_station_app

`zykh_station_app` 是“智药康护”本机主应用。本机负责现代化界面、业务编排、本地数据、安全规则和取药确认；QSM368ZP-WF 作为外设采集、执行控制及离线模型网关，通过本机转发端口接入。

已废弃的 `jetson_app/` 已从仓库移除。`zykh_app/` 仅保留板端历史网关与硬件调试实现；主应用不 import 或依赖其源码。

## 已完成范围

- 本机 FastAPI 后端骨架；
- SQLite 连接和初始化框架；
- QSM real/mock 双模式客户端，默认 real；
- 首页、药品页、问询页、记录页；
- 药品页取药确认，默认调用真实外设网关并保留本地记录；
- AI应急问询、风险提示、药品信息匹配、禁忌核验；
- QSM 上运行的 llama.cpp + Qwen3.5 离线问询模型，支持云端失败自动切换；
- QSM 上运行的 sherpa-onnx 中文离线 TTS，本地模式不访问云端语音服务；
- 本地记录聚合和待同步队列；
- QSM real/mock 接入验证接口。
- 体征读取、扫码识别、真实取药确认联调和外设能力展示入口。
- 真实设备联调检查脚本和终端内系统检查入口。
- QSM UART8 综合体征模块，支持心率、血氧、血压参考、呼吸频率和 HRV 数据。
- QSM 摄像头实时预览、条码连续核验、FF Camera 麦克风采集和板端人脸身份确认。
- 取药、问询和今日用药自动关联本次确认的服务对象；未知人脸不会自动建档，需由管理员绑定或录入。
- 终端空闲后进入唤醒页；下一位用户轻触屏幕后会清除上一位身份并重新进行人脸确认。

## 安全边界

系统只提供应急问询、风险提示、药品信息匹配、禁忌核验、取药确认和安全出药执行能力。涉及中高风险、禁忌风险、重复服药风险或信息不足时，应转由专业人员处理。

## 运行方式

后端：

```bash
cd zykh_station_app
python -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
sh scripts/start_backend.sh
```

前端：

```bash
cd zykh_station_app/frontend
npm install
npm run dev
```

一键启动两个本机服务：

```bash
cd zykh_station_app
sh scripts/start_all.sh
```

访问：

```text
http://127.0.0.1:5173
```

11 寸横屏全屏打开：

```bash
cd zykh_station_app
sh scripts/launch_kiosk.sh
```

`launch_kiosk.sh` 会检查并启动后端、前端，尝试把显示器切到 `1280x720`，然后用 Chromium kiosk 模式全屏打开页面。可选参数：

```bash
KIOSK_OUTPUT=HDMI-1 KIOSK_WIDTH=1280 KIOSK_HEIGHT=720 sh scripts/launch_kiosk.sh
```

脚本会记录启动前的分辨率。浏览器退出、按 `Ctrl+C`、关闭终端或任务管理器发送退出信号时，会停止本机音频转发并自动恢复分辨率。独立清理守护进程也覆盖主启动脚本被强制终止的情况，兜底结果写入 `data/run/kiosk-cleanup.log`。若需要保留 kiosk 分辨率：

```bash
KIOSK_RESTORE_RESOLUTION=0 sh scripts/launch_kiosk.sh
```

脚本默认加了 Chromium 兼容参数，避免部分设备上出现 `ANGLE/EGL failed to create drawable` 这类图形初始化错误。如需关闭这组兼容参数：

```bash
KIOSK_SAFE_GRAPHICS=0 sh scripts/launch_kiosk.sh
```

Chromium/Snap 的 GTK、GCM、GPU 等后台日志默认写入 `data/run/chromium.log`，终端只显示启动流程。如需直接在终端看浏览器日志：

```bash
KIOSK_BROWSER_LOG=terminal sh scripts/launch_kiosk.sh
```

如果本机服务已经启动，只想全屏打开浏览器，可以运行：

```bash
sh scripts/open_kiosk.sh
```

## 配置

默认配置见 `backend/.env.example`：

```text
QSM_MODE=real
QSM_BASE_URL=http://127.0.0.1:18080
QSM_TIMEOUT_SECONDS=5
QSM_FACE_BASE_URL=http://127.0.0.1:18081
QSM_MIC_BASE_URL=http://127.0.0.1:18082
QSM_VITALS_PREFER_FULL=false
DISPENSE_DRY_RUN=false
ENABLE_REAL_DISPENSE=1
AI_MODE=auto
AI_API_BASE=https://api.deepseek.com/chat/completions
AI_MODEL=deepseek-v4-flash
AI_CONNECTIVITY_TIMEOUT_SECONDS=2
LOCAL_AI_BASE_URL=http://127.0.0.1:18083
LOCAL_AI_MODEL=Qwen3.5-0.8B-Q4_K_M
```

real 模式用于本机访问外设网关。如果 real 模式不可用，后端返回结构化错误并让首页显示“暂不可用”，不会用假体征或假识别结果掩盖问题。`QSM_MODE=mock` 只保留为本地闭环检查选项。

当前硬件分工：摄像头、FF Camera 麦克风、体征、音频和药仓控制均接在 QSM。主机通过 `/api/camera/stream` 代理 QSM 的 MJPEG 画面，并把最近真实帧提供给扫码识别；不会回退到固定示例图。QSM 麦克风采集网关把 `S16_LE/16kHz/单声道` PCM 流转发给本机实时语音识别链路。人脸特征提取和比对在 QSM 运行，主机 SQLite 只保存不含生物特征的服务对象映射。

身体状态测量页通过 `/api/vitals/read-all` 同时读取 GY-614 额温和 QSM UART8 综合体征模块。综合模块使用 `/dev/ttyS8`、9600 8N1；药柜继续使用 `/dev/ttyS5`，两者互不占用。血压、呼吸频率和 HRV 统一作为健康状态辅助参考，不作为诊断依据。

首次部署或更新板端体征读取器时执行：

```bash
cd zykh_station_app
sh scripts/deploy_qsm_gateway.sh
```

该脚本会部署 `qsm_gateway/read_vitals_uart8.pl`、主网关启动包装、人脸识别网关和麦克风采集网关。检测到 `/home/jetson/QSM368ZP-board-face-recognition(1).zip`（或 `QSM_FACE_BUNDLE` 指定文件）时，还会部署板端运行库与模型。新模块温度按“整数 + 小数字节/100”解析为指温参考，额温仍以 GY-614 结果为准。心率、血氧和额温作为本页核心测量值；三项齐全即判定测量完成。血压、呼吸、HRV 和指温等字段仅在模块实际生成后展示，不会因辅助字段缺失误报测量失败，也不会通过估算补值。

当前 InspireFace 社区模型许可仅限学术用途；用于商业产品前必须替换为具有相应授权的模型。

AI 云通道兼容 DeepSeek OpenAI-style Chat Completions。密钥只从环境变量或本机私有文件读取，例如：

```bash
export AI_API_KEY_FILE=/userdata/zykh_app/data/ai-api-key.txt
```

`AI_MODE=auto` 默认先调用云端；密钥缺失、网络不可达或云请求失败时，会自动调用 QSM 上真实运行的 Qwen3.5 GGUF 模型。只有 QSM 离线模型也不可用时，才进入确定性的安全规则兜底。真实密钥只放在环境变量或 `backend/.env.local` 等本机私有文件，不能写入 Git、Markdown 或前端代码。

首次下载和部署离线模型：

```bash
cd zykh_station_app
sh scripts/download_offline_model.sh
sh scripts/deploy_offline_ai.sh
```

完整模型来源、哈希、资源占用、安全边界和断网验收见 [`docs/offline-ai.md`](docs/offline-ai.md)。

首次部署板端离线中文语音模型：

```bash
cd zykh_station_app
INSTALL_GATEWAY=1 PLAYBACK_TEST=1 sh scripts/deploy_offline_tts.sh
```

本地模式会强制使用板端 `sherpa-onnx`；联网模式优先使用云端 TTS，云端失败时自动回退板端模型。模型包不会提交到 Git。部署、接口和许可边界见 [`docs/offline-tts.md`](docs/offline-tts.md)。

## QSM 4G 联网

日常联网优先使用 QSM 上的 EC200A/SIM 数据链路。进入 QSM shell 后运行：

```bash
/userdata/zykh_app/scripts/start_4g.sh
```

仓库内提供同名脚本模板：

```bash
sh scripts/start_4g.sh
```

该脚本会检查 Quectel USB 设备、`/dev/ttyUSB*`、`usb0`、DHCP、默认路由、DNS、IP/DNS/HTTP 连通性。Wi-Fi 与 SIM 链路均不可用时，问询自动使用 QSM 离线模型；模型进程也不可用时才由安全规则继续处理。

## QSM real 模式验证

主外设网关、人脸识别网关、麦克风采集网关和离线模型分别转发到 `http://127.0.0.1:18080`、`http://127.0.0.1:18081`、`http://127.0.0.1:18082` 与 `http://127.0.0.1:18083`：

```bash
cd zykh_station_app
sh scripts/adb_forward.sh
```

转发成功后启动后端：

```bash
QSM_MODE=real QSM_BASE_URL=http://127.0.0.1:18080 sh scripts/start_backend.sh
```

默认真实开柜联动：`DISPENSE_DRY_RUN=false` 且 `ENABLE_REAL_DISPENSE=1`。取药确认仍必须勾选安全确认，后端会核对药品、仓位和库存，然后调用外设网关 `/api/dispense`。如需限制测试仓位，可设置 `REAL_DISPENSE_TEST_SLOT=1`；如需演示 dry-run，可临时设置 `DISPENSE_DRY_RUN=true`。

## 演示前检查

启动后端后可以执行：

```bash
cd zykh_station_app
sh scripts/check_devices.sh
curl http://127.0.0.1:8000/api/device/check
curl http://127.0.0.1:8000/api/ai/status
```

前端右上角有“系统检查”入口，显示当前模式、外设网关连接、外设摄像头、体征模块、出药联动和同步状态。普通终端 UI 不显示开发连接细节。

## 动效系统

终端默认使用静态 Lucide 图标。顶部品牌 Logo 只播放一次路径绘制；体征测量、扫码核验、语音录入和问询分析仅在对应任务进行时正反往复绘制，任务结束立即恢复同一个静态图标。息屏页中央唤醒图标持续轻量往复，背景只做低对比度呼吸变化；首页快捷入口保持静态。校验命令：

```bash
cd zykh_station_app/frontend
npm run test:motion
```

接入白名单、状态启停和无障碍边界见 [`docs/motion-system.md`](docs/motion-system.md)。网络、导航、返回、结果和同步等图标保持静态，避免持续动效干扰触摸操作。

## 真实硬件 smoke

不会触发真实取药的接口：

```bash
curl http://127.0.0.1:8000/api/qsm/status
curl http://127.0.0.1:8000/api/identity/status
curl -X POST http://127.0.0.1:8000/api/identity/resolve
curl -X POST http://127.0.0.1:8000/api/vitals/read-all
curl -X POST http://127.0.0.1:8000/api/audio/beep
curl -X POST http://127.0.0.1:8000/api/camera/capture
curl -X POST http://127.0.0.1:8000/api/medicine/scan
curl -X POST http://127.0.0.1:8000/api/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"轻微咳嗽一天，需要风险提示"}]}'
curl http://127.0.0.1:8000/api/qsm/capabilities
curl http://127.0.0.1:8000/api/device/check
```

真实取药确认会调用外设网关。测试前请确认柜门附近安全：

```bash
curl -X POST http://127.0.0.1:8000/api/dispense/confirm \
  -H "Content-Type: application/json" \
  -d '{"medicine_id":"aspirin-enteric","slot":"A01","quantity":1,"reason":"真实联调确认","confirmed_safety_notice":true,"confirm_real_dispense":true}'
```

## 验证

```bash
python -m compileall zykh_station_app/backend/app
cd zykh_station_app/frontend && npm run test:motion && npm run build
```

## 阶段计划

1. 首页闭环和新架构基线；
2. 药品页 + 取药确认流程；
3. 问询页 + AI rules 兜底；
4. 记录页 + 同步队列；
5. QSM real/mock 双模式接入验证；
6. QSM 外设功能联调入口；
7. 真实设备联调与演示稳定化；
8. 真实外设接入与逐页截图验收。
