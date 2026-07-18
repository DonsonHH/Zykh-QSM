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
- QSM 上运行的 sherpa-onnx 中文实时语音识别与常驻离线 TTS，本地模式不访问云端语音服务；
- 联网时使用 Qwen3 实时 TTS 增量 PCM，边生成边送入 QSM 喇叭；
- 本地记录聚合和待同步队列；
- QSM real/mock 接入验证接口。
- 体征读取、扫码识别、真实取药确认联调和外设能力展示入口。
- 真实设备联调检查脚本和终端内系统检查入口。
- QSM UART8 综合体征模块，支持心率、血氧、血压参考、呼吸频率和 HRV 数据。
- QSM 摄像头实时预览、条码连续核验、FF Camera 麦克风采集和板端人脸身份确认。
- QSM AS608 指纹确认：指纹模板保留在模块内，本机只保存服务对象映射；取药时指纹确认成功即可记录使用人并开柜。
- 取药、问询和今日用药关联已确认的服务对象；取药按钮单击一次后自动完成指纹或面部核验、核对计划归属并打开对应柜门，不要求第二次点击。
- 今日用药计划支持每天、每隔若干天和每周指定日；计划前后 1 小时内息屏页会突出显示姓名、药品、时间与用量，同一时段有多人待取药时自动轮播，其余时间显示常态心脏动效。
- 药品页按功效区分图标，并展示功能主治、用法用量和禁忌提醒；23 项固定资料按独立版本迁移且不重置库存，来源与维护边界见 [家庭药柜说明资料来源](docs/medicine-reference.md)。
- 未识别到已登记人脸的访客完成确认并真实取药时，会从识别预览保留一张低分辨率现场图，供受保护的管理员调试台追溯；留档失败不阻断开柜。
- 家庭取药记录只展示真实成功开柜的记录，并明确区分已登记服务对象与游客；dry-run 和失败记录仅保留在调试审计接口。
- 终端空闲后进入唤醒页；下一位用户轻触屏幕后会清除上一位身份并重新进行人脸确认。
- 面向家庭用户的终端设置页自动保存 Wi-Fi、数据网络、问询模式、音量、亮度和自动息屏等真实控制；独立管理员调试台负责人员、生物识别、今日用药、药柜、设备与实时日志维护。

## 安全边界

系统只提供应急问询、风险提示、药品信息匹配、禁忌核验、取药确认和安全出药执行能力。低风险和中风险可展示通过库存、OTC、有效期与禁忌核验的一个优先方案及最多一个备选方案；高风险和紧急风险不展示方案，并提示联系医生或救援人员。模型只整理证据和提出下一步动作意图，风险、方案和开柜权限由本地确定性规则控制。用户选择一个互斥方案、确认安全提示并完成 3 秒可取消倒计时后，后端会再次核验当前状态，再通过既有开柜服务执行所选方案。该流程不替代诊断或处方。

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

## 微信小程序与云同步

FastAPI 后台按 2 秒周期向现有 CloudBase 环境上报药品、体征、服务对象、计划、问询和取药记录，并拉取小程序命令。网络中断不影响本地使用，恢复后自动补传。

```bash
curl http://127.0.0.1:8000/api/sync/status
curl -X POST http://127.0.0.1:8000/api/sync/run
```

云函数源码、部署脚本和远程命令说明见 [docs/cloudbase-sync.md](docs/cloudbase-sync.md)。

## 配置

默认配置见 `backend/.env.example`：

```text
QSM_MODE=real
QSM_BASE_URL=http://127.0.0.1:18080
QSM_VITALS_BASE_URL=http://127.0.0.1:18085
QSM_TIMEOUT_SECONDS=5
QSM_FACE_BASE_URL=http://127.0.0.1:18081
QSM_MIC_BASE_URL=http://127.0.0.1:18082
QSM_FINGERPRINT_BASE_URL=http://127.0.0.1:18086
QSM_LOCAL_ASR_URL=ws://127.0.0.1:18084
QSM_VITALS_PREFER_FULL=false
DISPENSE_DRY_RUN=false
ENABLE_REAL_DISPENSE=1
AI_MODE=auto
AI_API_BASE=https://api.deepseek.com/chat/completions
AI_MODEL=deepseek-v4-flash
AI_ENABLE_THINKING=true
AI_CONNECTIVITY_TIMEOUT_SECONDS=2
INQUIRY_SPO2_EMERGENCY_BELOW=90
INQUIRY_SPO2_HIGH_MAX=93
INQUIRY_TEMPERATURE_HIGH_AT=39
INQUIRY_MEDIUM_CONFIDENCE_BELOW=0.65
LOCAL_AI_BASE_URL=http://127.0.0.1:18083
LOCAL_AI_MODEL=Qwen3.5-0.8B-Q4_K_M
CLOUD_SYNC_ENABLED=true
CLOUD_SYNC_DEVICE_ID=zykh-qsm-001
CLOUD_SYNC_INTERVAL_SECONDS=2
ADMIN_DEBUG_PIN=1145
ADMIN_SESSION_MINUTES=30
```

## 终端设置与管理员调试

终端右上角设置页用于家庭用户直接调整 Wi-Fi 与数据网络开关、联网优先/本地问询、外放和麦克风音量、显示亮度及自动息屏时间。操作停止 900ms 后自动串行保存，连续拖动滑块不会并发调用硬件。数据网络区域显示 QSM 实际运营商和 `AT+CNUM` 返回的号码；模块未提供号码时明确显示未提供。

设置页中的“管理员调试”进入独立鼠标操作界面。管理员口令验证后可查看运行概览、维护服务对象及人脸/指纹绑定、编辑今日用药计划和 23 个药仓、现场开柜、检查设备、控制屏幕、重启应用以及查看实时脱敏日志。管理员令牌只保存在浏览器 `sessionStorage`，默认 30 分钟失效；开柜、删除、息屏和重启使用普通二次确认，并写入 `admin_audit_records`。人脸录入提供实时取景预览，指纹录入显示准备、采集与结果状态。

部署前必须在 `backend/.env.local` 修改默认口令：

```text
ADMIN_DEBUG_PIN=请设置独立口令
ADMIN_SESSION_MINUTES=30
ADMIN_ALLOW_SYSTEM_ACTIONS=true
```

系统操作只执行后端配置的固定命令，前端不能提交任意 shell 命令。应用重启默认执行 `scripts/admin_restart_app.sh`；整机重启默认使用 `sudo -n systemctl reboot`，需要提前按部署环境配置最小化 sudo 权限。管理员入口不应暴露到公网。

real 模式用于本机访问外设网关。如果 real 模式不可用，后端返回结构化错误并让首页显示“暂不可用”，不会用假体征或假识别结果掩盖问题。`QSM_MODE=mock` 只保留为本地闭环检查选项。

当前硬件分工：摄像头、FF Camera 麦克风、AS608 指纹模块、体征、音频和药仓控制均接在 QSM。主机通过 `/api/camera/stream` 代理 QSM 的 MJPEG 画面，并把最近真实帧提供给扫码识别；不会回退到固定示例图。QSM 麦克风采集网关输出 `S16_LE/16kHz/单声道` PCM；联网时由云端实时识别，本地模式由 QSM 上的 sherpa-onnx WebSocket 服务逐段识别。人脸特征提取和比对在 QSM 运行，指纹模板保留在 AS608 内，主机 SQLite 只保存不含原始生物特征的服务对象映射。

身体状态测量页使用 `/api/vitals/session/*` 会话接口并行读取 GY-614 额温和 QSM UART8 综合体征模块。状态依次为 `starting → waiting_finger → stabilizing → complete/failed/cancelled`；板端成功写出 `0x24` 后才确认硬件已启动，完成、取消和异常均发送 `0x2A`。综合模块使用 `/dev/ttyS8`、9600 8N1；药柜继续使用 `/dev/ttyS5`，两者互不占用。心率、血氧、额温三项齐全才完成测量；血压、呼吸频率和 HRV 仅作辅助参考。

首次部署或更新板端体征读取器时执行：

```bash
cd zykh_station_app
sh scripts/deploy_qsm_vitals.sh
```

该脚本只部署 `read_vitals_uart8.pl` 和独立的 8085 体征会话网关，并建立本机 `18085 → 8085` 转发，不扰动已经工作的摄像头、人脸、麦克风和指纹服务。完整外设首次部署仍使用 `scripts/deploy_qsm_gateway.sh`。新模块温度按“整数 + 小数字节/100”解析为指温参考，额温仍以 GY-614 结果为准。血压、呼吸、HRV 和指温等字段仅在模块实际生成后展示，不会因辅助字段缺失误报测量失败，也不会通过估算补值。

当前 InspireFace 社区模型许可仅限学术用途；用于商业产品前必须替换为具有相应授权的模型。

AI 云通道兼容 DeepSeek OpenAI-style Chat Completions。密钥只从环境变量或本机私有文件读取，例如：

```bash
export AI_API_KEY_FILE="$PWD/backend/data/ai-api-key.txt"
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

继续部署常驻离线 TTS 和本地实时语音识别服务：

```bash
sh scripts/deploy_local_tts_server.sh
sh scripts/deploy_local_asr.sh
```

本地模式会使用板端中文流式 Zipformer Transducer、领域热词和 `modified_beam_search`；前端只有在识别会话与麦克风均就绪后才显示“正在听”。联网模式使用 `qwen3-asr-flash-realtime`。识别模式直接读取当前终端模式，云会话和 QSM 麦克风并行准备，不在按键关键路径重复执行完整 SIM/AT 探测。语音播报默认使用适中语速 `1.32`：联网时使用 `qwen3-tts-instruct-flash-realtime-2026-01-22` 并将音频增量写入 QSM PCM 播放流，按 24kHz PCM 时长等待未播放尾音进入 DAC 后才停止流；失败时自动回退常驻板端模型。模型包不会提交到 Git。部署、接口和许可边界见 [`docs/offline-tts.md`](docs/offline-tts.md)。

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

主外设网关、人脸识别网关、麦克风采集网关、离线语言模型、离线实时语音识别和指纹网关分别转发到 `18080`、`18081`、`18082`、`18083`、`18084` 与 `18086`；实时 PCM 外放使用 `19001`：

```bash
cd zykh_station_app
sh scripts/adb_forward.sh
```

转发成功后启动后端：

```bash
QSM_MODE=real QSM_BASE_URL=http://127.0.0.1:18080 sh scripts/start_backend.sh
```

默认真实开柜联动：`DISPENSE_DRY_RUN=false` 且 `ENABLE_REAL_DISPENSE=1`。用户在取药弹窗单击“确认身份并开柜”后，界面自动完成指纹或面部确认；若该操作来自今日计划，还会核对识别到的服务对象、药品与计划，随后直接调用外设网关 `/api/dispense`。如需限制测试仓位，可设置 `REAL_DISPENSE_TEST_SLOT=1`；如需演示 dry-run，可临时设置 `DISPENSE_DRY_RUN=true`。

AS608 原始指纹模板只保存在模块内部，人脸特征由 QSM 本地识别组件保存。主机 SQLite 仅保存模板/主体与服务对象的映射、确认次数、最近确认时间及“谁在何时取走什么药”的记录，不保存原始指纹图像或摄像头视频。

当前实机 AS608 兼容模块对 Aura LED 指令 `0x35` 返回 `unsupported`。软件会在息屏时尝试待机灯控，但四线 USB-TTL 连接不能切断模块照明电源；若硬件必须完全灭灯，需要按模块资料把 `Vt/WAK` 触摸供电线接入可控电源或 GPIO。识别、录入和模板保存不受此限制。

## 演示前检查

启动后端后可以执行：

```bash
cd zykh_station_app
sh scripts/check_devices.sh
curl http://127.0.0.1:8000/api/device/check
curl http://127.0.0.1:8000/api/ai/status
```

前端右上角有“系统检查”入口，显示当前模式、外设网关连接、外设摄像头、体征模块、出药联动和同步状态。顶栏使用手机式 Wi-Fi/4G 信号图标，并在真实 API 请求发送和返回时点亮上下行箭头；本地模式只显示飞行模式。普通终端 UI 不显示开发连接细节。

## 动效系统

终端默认使用静态 Lucide 图标。顶部使用“房屋、药片、心电与无线”品牌线稿，进入页面或再次触屏时播放一次路径绘制；体征测量、扫码核验、语音录入和问询分析仅在对应任务进行时正反往复绘制，任务结束立即恢复同一个静态图标。息屏页中央使用同一品牌线稿持续轻量往复，背景只做低对比度呼吸变化；首页快捷入口保持静态。校验命令：

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
curl http://127.0.0.1:8000/api/fingerprint/status
curl -X POST http://127.0.0.1:8000/api/identity/resolve
curl -X POST http://127.0.0.1:8000/api/vitals/session/start
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
