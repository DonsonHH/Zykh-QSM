# zykh_station_app

`zykh_station_app` 是“智药康护”本机主应用。本机负责现代化界面、业务编排、本地数据、安全规则和取药确认；QSM368ZP-WF 作为外设采集、执行控制及离线语音网关，通过本机转发端口接入。

已废弃的 `jetson_app/` 已从仓库移除。`zykh_app/` 仅保留板端历史网关与硬件调试实现；主应用不 import 或依赖其源码。

## 已完成范围

- 本机 FastAPI 后端骨架；
- SQLite 连接和初始化框架；
- QSM real/mock 双模式客户端，默认 real；
- 首页、药品页、问询页、记录页；
- 药品页取药确认，默认调用真实外设网关并保留本地记录；
- AI应急问询、风险提示、药品信息匹配、禁忌核验；
- 联网和本地演示模式共用 DeepSeek 云端问询链路；本地确定性规则负责危险信号和失败时的安全连续性，不生成伪模型结论；
- QSM 上运行 sherpa-onnx Paraformer 中文离线语音识别与 Sherpa-ONNX 中文离线 TTS；联网模式使用云端实时 TTS，本地模式使用板端离线 TTS；
- 联网时使用 Qwen3 实时 TTS 增量 PCM，边生成边送入 QSM 喇叭；
- 本地记录聚合和待同步队列；
- QSM real/mock 接入验证接口。
- 体征读取、扫码识别、真实取药确认联调和外设能力展示入口。
- 真实设备联调检查脚本和终端内系统检查入口。
- QSM UART8 综合体征模块，支持心率、血氧、血压参考、呼吸频率和 HRV 数据。
- QSM 摄像头实时预览、条码连续核验、FF Camera 麦克风采集和板端人脸身份确认。
- QSM AS608 指纹确认：指纹模板保留在模块内，本机只保存服务对象映射；成功匹配会签发短时身份断言，供后续用药核查使用。
- 今日计划、AI 问询和药品页自助取药是三条隔离路径。药品页先确认已登记人物，再由后端核查人物档案、药品审核事实、库存、仓位和有效期；只有短时 `PASSED` 结果在用户再次确认说明后才能开柜。`BLOCKED`、`CHECK_FAILED`、访客或资料变化都不会调用 QSM。
- 今日用药计划支持每天、每隔若干天和每周指定日；计划前后 1 小时内息屏页会突出显示姓名、药品、时间与用量，同一时段有多人待取药时自动轮播，其余时间显示常态心脏动效。
- 药品页按功效区分图标，并展示功能主治、用法用量和禁忌提醒；23 项固定资料按独立版本迁移且不重置库存，来源与维护边界见 [家庭药柜说明资料来源](docs/medicine-reference.md)。
- 未识别到已登记档案的访客不能通过药品页自助取药；系统返回 `PROFILE_UNAVAILABLE / CHECK_FAILED` 并明确显示柜门未打开。
- 家庭取药记录只展示真实成功开柜的记录，并明确区分已登记服务对象与游客；dry-run 和失败记录仅保留在调试审计接口。
- 终端空闲后进入唤醒页；下一位用户轻触屏幕后会清除上一位身份并重新进行人脸确认。
- 面向家庭用户的终端设置页自动保存联网/本地显示与同步模式、音量、亮度和自动息屏；真实 Wi-Fi 与数据网络控制位于独立管理员调试台，调试台同时负责人员、生物识别、今日用药、药柜、设备与实时日志维护。

## 安全边界

系统只提供应急问询、风险提示、药品信息匹配、禁忌核验、取药确认和安全出药执行能力。低风险和中风险可展示通过库存、有效期与禁忌核验的 OTC 药品；处方药只有在该服务对象当天已有待执行用药计划时才进入候选，并在开柜时再次核验同一计划。每次最多展示一个优先方案和一个备选方案；高风险和紧急风险不展示方案，并提示联系医生或救援人员。模型负责整理证据、提出下一步动作并在已通过硬性安全过滤的候选内生成分析与排序；危险信号拦截、候选准入、禁忌复核和开柜权限仍由本地确定性规则控制。用户选择一个互斥方案、确认安全提示并完成 3 秒可取消倒计时后，后端会再次核验当前状态，再通过既有开柜服务执行所选方案。该流程不替代诊断或处方。

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

`launch_kiosk.sh` 会检查并启动后端、前端，保留显示器当前分辨率，并用 Chromium kiosk 模式以 `200%` 进程级缩放全屏打开页面。缩放只属于本次 Chromium 进程，浏览器正常退出、启动器被终止或整个任务组被停止后都会自动消失，不会修改桌面系统的缩放设置。可选调整缩放：

```bash
KIOSK_SCALE=1.5 sh scripts/launch_kiosk.sh
```

只有明确需要兼容旧设备时才切换显示模式；退出时会恢复启动前分辨率：

```bash
KIOSK_CHANGE_RESOLUTION=1 KIOSK_OUTPUT=HDMI-1 KIOSK_WIDTH=1280 KIOSK_HEIGHT=720 sh scripts/launch_kiosk.sh
```

脚本默认启动 Fcitx5 供实体键盘使用，并使用不依赖 X11/Wayland 桌面协议的应用内屏幕键盘。文本布局默认进入离线中文拼音模式，带候选词、翻页和中英切换；数字字段仍使用独立数字布局。拼音词库仅在首次打开中文文本键盘时按需加载，不增加首页的初始渲染负担。接入实体键盘或不需要屏幕键盘时可关闭：

```bash
KIOSK_TOUCH_KEYBOARD=0 sh scripts/launch_kiosk.sh
```

浏览器退出、按 `Ctrl+C`、关闭终端或任务管理器发送退出信号时，脚本会停止本机音频转发；独立清理守护进程也覆盖主启动脚本被强制终止的情况，兜底结果写入 `data/run/kiosk-cleanup.log`。仅当启用了 `KIOSK_CHANGE_RESOLUTION=1` 时，脚本才记录并恢复启动前分辨率。若显式切换后仍要保留 kiosk 分辨率：

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

## 家庭演示人物与计划

受控迁移会新建两个独立人物 ID：`wang-nainai`（王奶奶，72 岁）和
`li-yeye`（李爷爷，74 岁），并分别维护结构化病史、当前用药、过敏事实、
`safety_profile_revision` 与 `persona_generation=senior-demo-v1`。旧的张三、
李四、王五演示人物只做归档，既有问询与生物特征仍留在原 ID，绝不改名或
复用给新人物。

演示计划固定为四条：王奶奶 08:00 氨氯地平、21:00 布地奈德鼻喷雾剂；
李爷爷 07:30 乳果糖、20:30 枸地氯雷他定。种子只补缺失记录，不覆盖管理
员已经调整的时间、剂量或完成状态，也不会在人物缺失时回退绑定到任意用户。
记录页人物卡可打开该人物自己的问询摘要时间线；归档人物不出现在普通列表，
但其历史仍可按明确 ID 读取。归档人物关联的旧计划同步归档，不能重新显示、
编辑或进入开柜路径。

## 微信小程序与云同步

FastAPI 后台按 2 秒周期向现有 CloudBase 环境上报药品、体征、服务对象、计划、问询和真实取药记录，并拉取允许的非开柜命令。心跳中的近期问询只发送摘要和消息数；完整数据走独立快照集合。一次人物—药品核查只对应一条稳定安全事件：拦截/核查失败在核查终态进入 append-only outbox，通过项则等开柜终态后把核查与物理结果合并上报为同一条 `medication_safety_events`，不会混入取药记录，也不会被 `FINALIZE_SNAPSHOT` 删除。网络中断不影响本地拦截，恢复后按 `event_id + payload_digest` 幂等补传。
CloudBase 2.5 要求所有健康数据读取先通过 ACTIVE membership，并按人物范围隔离人物、计划、问询、记录、体征和安全事件；安全事件还要求 `READ_SAFETY`。问询详情沿用同一范围，越权不泄露是否存在。通用命令的 request ID 在事务中绑定请求摘要，只读家属不能下发命令。小程序侧只有只读安全事件能力；`OPEN_CABINET` 已从云端允许列表、内嵌 helper 和板端执行器中移除，历史命令也会失败关闭且不触碰 QSM。Station 上报必须携带服务端配置的设备密钥，缺少密钥时失败关闭。
设备绑定通过当前微信 OPENID 兑换服务端 SHA-256 定位的一次性、限时配对码；事务只从配对文档授予角色、人物范围和权限，调用者输入的 deviceId 不构成授权。安全事件上报会给当时有效的家属幂等写入最小化通知 outbox，但不等待或伪造微信推送成功。本仓只提供云函数与嵌入 helper；配对码生成管理端、实际小程序页面、数据库规则/索引、订阅消息模板和发送 worker 仍需在外部工程接入并部署验收。
小程序下发 `AUDIO_SPEAK` 时，终端会把姓名和药品名称整理成服药提醒并通过 QSM 喇叭播报；小程序端无需访问终端局域网地址。

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
QSM_VITALS_PREPARE_PATH=/api/vitals/prepare
QSM_TIMEOUT_SECONDS=5
QSM_FACE_BASE_URL=http://127.0.0.1:18081
QSM_MIC_BASE_URL=http://127.0.0.1:18082
QSM_FINGERPRINT_BASE_URL=http://127.0.0.1:18086
QSM_LOCAL_ASR_URL=ws://127.0.0.1:18084
QSM_VITALS_PREFER_FULL=false
DISPENSE_DRY_RUN=false
ENABLE_REAL_DISPENSE=1
AI_MODE=cloud
AI_API_BASE=https://api.deepseek.com/chat/completions
AI_RESPONSES_API_BASE=https://api.deepseek.com/responses
AI_MODEL=deepseek-v4-flash
AI_ENABLE_THINKING=true
AI_INQUIRY_REASONING_EFFORT=high
AI_CONNECTIVITY_TIMEOUT_SECONDS=2
INQUIRY_SPO2_EMERGENCY_BELOW=90
INQUIRY_SPO2_HIGH_MAX=93
INQUIRY_TEMPERATURE_HIGH_AT=39
INQUIRY_MEDIUM_CONFIDENCE_BELOW=0.65
OFFLINE_INQUIRY_MODE=rules
NETWORK_KEEP_SIM_TRANSPORT_WHEN_HIDDEN=true
VITALS_DEMO_SPO2_FALLBACK=true
CLOUD_SYNC_ENABLED=true
CLOUD_SYNC_DEVICE_ID=zykh-qsm-001
CLOUD_SYNC_INTERVAL_SECONDS=2
ADMIN_DEBUG_PIN=1145
ADMIN_SESSION_MINUTES=30
```

## 终端设置与管理员调试

终端右上角设置页用于调整联网/本地模式、外放和麦克风音量、显示亮度及自动息屏时间。联网模式保持微信小程序实时同步并使用云端语音，本地模式暂停实时同步并使用 QSM 离线语音；两种模式都保留实际联网能力并使用同一云端问询模型。普通界面不展示内部模型或语音提供方。外放音量以 0–100% 展示：0% 为静音，1–100% 通过 `20*log10` 分贝曲线映射到当前校准的 128–255 原始增益区间，并以同一百分比控制主机音频转发；旧版 1–127 增益会按原滑块位置一次性迁移，音频转发重启后会恢复已保存音量。操作停止 900ms 后自动串行保存，连续拖动滑块不会并发调用硬件。

设置页中的“管理员调试”进入独立鼠标操作界面。管理员口令验证后可查看运行概览、真实开关 Wi-Fi 和 QSM 数据网络、维护服务对象及人脸/指纹绑定、编辑今日用药计划和 23 个药仓、现场开柜、检查设备、控制屏幕、重启应用以及查看实时脱敏日志。管理员令牌只保存在浏览器 `sessionStorage`，默认 30 分钟失效；开柜、删除、息屏和重启使用普通二次确认，并写入 `admin_audit_records`。人脸录入提供实时取景预览，指纹录入显示准备、采集与结果状态。

部署前必须在 `backend/.env.local` 修改默认口令：

```text
ADMIN_DEBUG_PIN=请设置独立口令
ADMIN_SESSION_MINUTES=30
ADMIN_ALLOW_SYSTEM_ACTIONS=true
```

系统操作只执行后端配置的固定命令，前端不能提交任意 shell 命令。应用重启默认执行 `scripts/admin_restart_app.sh`；整机重启默认使用 `sudo -n systemctl reboot`，需要提前按部署环境配置最小化 sudo 权限。管理员入口不应暴露到公网。

real 模式用于本机访问外设网关。如果 real 模式不可用，后端返回结构化错误并让首页显示“暂不可用”，不会用假体征或假识别结果掩盖问题。`QSM_MODE=mock` 只保留为本地闭环检查选项。

当前硬件分工：摄像头、FF Camera 麦克风、AS608 指纹模块、体征、音频和药仓控制均接在 QSM。主机通过 `/api/camera/stream` 代理 QSM 的 MJPEG 画面，并把最近真实帧提供给扫码识别；不会回退到固定示例图。QSM 麦克风采集网关输出 `S16_LE/16kHz/单声道` PCM；默认由云端实时识别，云端不可用时自动回退到 QSM 上的 sherpa-onnx WebSocket 服务。人脸特征提取和比对在 QSM 运行，指纹模板保留在 AS608 内，主机 SQLite 只保存不含原始生物特征的服务对象映射。

身体状态测量页进入时先调用 `/api/vitals/prepare` 启动传感器算法，点击“开始测量”后再通过 `/api/vitals/session/*` 采集本次新帧，并行读取 GY-614 额温和 QSM UART8 综合体征模块。状态依次为 `starting → waiting_finger → stabilizing → complete/failed/cancelled`；根据模块首次算法需要 5–10 秒、后续约每 1.28 秒更新一次的特性，冷启动累计稳定时间默认取 8 秒，页面预热时间会从中扣除，但正式采样仍至少保留 3 秒。采样会丢弃预热阶段缓存，并要求近期窗口内心率、血氧各有 2 帧有效值，避免相隔很久的旧值拼成一次结果。已有稳定心率但血氧仍为零时只延长一次血氧计算窗口并自动重测一次；重测前会同步取消旧会话、等待 UART 释放，再启动新会话，因此不会出现上一轮测量仍占用设备的错误。问询页在语音引导开始时即预热硬件，与首页入口使用同一套会话。前端按 `failure_reason` 区分无协议帧、无手指、信号未稳定、额温缺失和通信中断；单次或连续第二次 `transport_error` 会保留原 session 并在 700ms 后重试，任一正常状态会清零计数，只有用户明确取消或连续第三次通信失败才请求板端停止。完成、取消、异常及无人操作的预热超时均发送 `0x2A`。综合模块使用 `/dev/ttyS8`、9600 8N1；药柜继续使用 `/dev/ttyS5`，两者互不占用。心率、血氧、额温三项齐全才完成测量；血压、呼吸频率和 HRV 仅作辅助参考。随机演示血氧只用于现场演示，不会写入真实体征记录或云同步。手指信号失败时，本次会话保持 `failed`，历史完整体征仅作为独立参考展示，不会与本次额温拼成完成结果。Phase 3 不调整 18 秒测量、12 秒接触稳定、8 秒血氧延长或 UART 协议。

AI 问询中的体征测量是当前问询会话的工具步骤。用户说明主要不适后，系统先确认是否还有同时出现的其他不适，再最多进行 4 次真正影响判断的症状澄清；编排器随后依次核对本次已用药和过敏/禁忌信息，再进入核心体征测量。症状信息已经足够时可以提前结束澄清；明确纠正主诉，或新增会改变判断的主要症状时，会针对更新后的主诉重新计算问题预算，但普通细化不会反复重置预算。完成、失败或取消都会写回原会话并由同一个模型继续，不通过浏览器临时存储拼接两个页面。

首次部署或更新板端体征读取器时执行：

```bash
cd zykh_station_app
sh scripts/deploy_qsm_vitals.sh
```

该脚本只部署 `read_vitals_uart8.pl` 和独立的 8085 体征会话网关，并建立本机 `18085 → 8085` 转发，不扰动已经工作的摄像头、人脸、麦克风和指纹服务。完整外设首次部署仍使用 `scripts/deploy_qsm_gateway.sh`。新模块温度按“整数 + 小数字节/100”解析为指温参考，额温仍以 GY-614 结果为准。血压、呼吸、HRV 和指温等字段仅在模块实际生成后展示，不会因辅助字段缺失误报测量失败，也不会通过估算补值。

当前 InspireFace 社区模型许可仅限学术用途；用于商业产品前必须替换为具有相应授权的模型。

AI 云通道使用 DeepSeek Chat Completions 完成逐轮语义抽取，最终分析与候选排序优先使用配置的 Responses 端点；Responses 只进行一次 12–15 秒的限时尝试，端点超时、不可用或返回无效结构时立即回退到同一云端模型的 Chat Completions JSON 契约。`AI_INQUIRY_REASONING_EFFORT` 统一控制逐轮抽取、Responses 最终分析和 Chat 回退，支持 `off`、`low`、`high`、`max`，默认 `high`。旧配置 `AI_INQUIRY_ENABLE_THINKING=true/false` 仅在新配置缺失时兼容映射为 `high/off`。最终分析返回带证据引用的结构化 assessment，任何药品仍必须通过本地确定性安全校验。密钥只从环境变量或本机私有文件读取，例如：

```bash
export AI_API_KEY_FILE="$PWD/backend/data/ai-api-key.txt"
```

生产配置固定使用云端模型；历史 `AI_MODE=auto|local` 与 `OFFLINE_INQUIRY_MODE=model` 会被解析为 `cloud + rules`，不会重新启用板端语言模型。云端缺少密钥、不可达、请求失败或结构无效时，确定性规则只维持追问和危险信号拦截；最终排序失败不会用规则生成或伪装 assessment，也不会返回药品候选。联网/本地模式的路由由后端统一处理，普通终端界面不暴露技术通道。管理员调试台中的 Wi-Fi 和数据网络开关直接控制真实接口；关闭 Wi-Fi 前仍会先验证 SIM 备用通道，避免终端失联。真实密钥只放在环境变量或 `backend/.env.local` 等本机私有文件，不能写入 Git、Markdown 或前端代码。

固定 23 仓使用 `database-safety-facts-v6-repaired-fixed-catalog` 受控资料版本，全部进入问询安全评估；实际候选仍会逐项检查实时库存、有效期、包装身份、说明资料以及处方/既往计划资格，过期或不满足资格的药品只会被评估后排除。动态扫码或云端换药仍从 `draft` 开始，不能继承固定仓身份的审核状态。

多药结果不能由模型自由拼接。后端只把当前病例精确命中的受控组合 ID、成员顺序和一次性授权指纹发给模型；当前内置方案限于浅表伤口的消毒覆盖流程，以及成人无危险信号水样腹泻的分时方案。模型返回后、结果展示前和每次开柜前都会重新核对病例条件、成员安全资料、成分冲突矩阵、库存与授权指纹；任一条件变化即停止原方案。

演示测量默认启用 `VITALS_DEMO_SPO2_FALLBACK=true`。只有心率、额温和手指接触均已由真实设备确认、且完整测量窗口内仅血氧未稳定时，系统才补入 `95-99` 的演示整数；会话会标记 `spo2_source=demo_fallback`，且不会保存或同步为真实测量，真实血氧一旦可用始终优先使用。

服务地点默认预设为成都。用户提到中暑、暴晒或高温不适时，云端问询会读取成都当前气温、体感温度和湿度作为环境背景；天气不能单独用于判断病因，也不能替代本次体征测量。相关配置为 `INQUIRY_LOCATION_NAME`、`INQUIRY_LOCATION_LATITUDE`、`INQUIRY_LOCATION_LONGITUDE` 和 `WEATHER_API_BASE`。

问询模型路由、规则回退和旧 QSM llama.cpp 资产边界见 [`docs/offline-ai.md`](docs/offline-ai.md)。首次部署 QSM 离线中文语音模型：

```bash
cd zykh_station_app
sh scripts/deploy_offline_tts.sh
```

`deploy_local_tts_server.sh` 保留为兼容入口并委托同一 QSM 部署。继续部署本地 Paraformer 语音识别服务：

```bash
sh scripts/deploy_local_asr.sh
```

`deploy_local_asr.sh` 从仓库根目录的 `QSM368ZP-offline-asr-migration*.zip` 校验并部署 Paraformer int8 模型，删除旧 Zipformer 目录，并预热板端 `6006` 常驻服务。云端识别不可用时会自动回退到本地 Paraformer。前端只有在识别服务与 QSM 麦克风都就绪后才显示“正在听”。离线识别部署和验收见 [`docs/offline-asr.md`](docs/offline-asr.md)。

语音播报默认使用适中语速 `1.32`：联网模式使用 `qwen3-tts-instruct-flash-realtime-2026-01-22` 并将音频增量写入 QSM PCM 播放流；本地模式直接调用 QSM 板端 Sherpa-ONNX VITS。云端合成失败也会安全回退到板端离线语音。模型包不会提交到 Git。部署、接口和许可边界见 [`docs/offline-tts.md`](docs/offline-tts.md)。

## QSM 4G 联网

日常联网优先使用 QSM 上的 EC200A/SIM 数据链路。进入 QSM shell 后运行：

```bash
/userdata/zykh_app/scripts/start_4g.sh
```

仓库内提供同名脚本模板：

```bash
sh scripts/start_4g.sh
```

该脚本会检查 Quectel USB 设备、`/dev/ttyUSB*`、`usb0`、DHCP、默认路由、DNS、IP/DNS/HTTP 连通性。Wi-Fi 与 SIM 链路均不可用时，问询保留本地危险信号拦截和安全失败提示，但不会伪装云端模型结论。`launch_kiosk.sh` 默认不启动旧 QSM 语言模型，并会幂等清退其已知进程，为板端离线语音和外设服务释放资源。普通界面不展示技术通道名称。

主机通过 QSM 的 USB RNDIS 接口使用该数据链路：QSM `usb0` 连接 EC200A，QSM `usb1` 连接主机，主机侧接口名为 `usb0`。首次启动终端时，`launch_kiosk.sh` 会请求一次管理员授权并安装受限路由助手。之后关闭 Wi-Fi 前，后端会先完成 QSM NAT、主机 `192.168.77.2/24` 地址和 metric 700 备用路由验证；任一步失败都会保留 Wi-Fi，避免终端失联。也可提前手动安装：

```bash
sudo sh scripts/install_qsm_tether_helper.sh
```

Wi-Fi 默认路由优先级高于 SIM；Wi-Fi 关闭或失效后才自动使用 QSM 数据网络。仅 QSM 自身联网但主机备用路由未通时，界面不会误报主机已使用 SIM。

## QSM real 模式验证

主外设网关、人脸识别网关、麦克风采集网关、离线 Paraformer 语音识别和指纹网关分别转发到 `18080`、`18081`、`18082`、`18084` 与 `18086`；其中主机 `18084` 对应板端 `6006`，实时 PCM 外放使用 `19001`。旧 `18083` 仅保留诊断兼容，不参与应用问询：

```bash
cd zykh_station_app
sh scripts/adb_forward.sh
```

转发成功后启动后端：

```bash
QSM_MODE=real QSM_BASE_URL=http://127.0.0.1:18080 sh scripts/start_backend.sh
```

默认真实开柜联动：`DISPENSE_DRY_RUN=false` 且 `ENABLE_REAL_DISPENSE=1`。今日计划和问询继续使用既有确认凭据；药品页自助取药必须依次调用 `/api/manual-medication-access/assess` 与 `/api/manual-medication-access/confirm`，不能直接借 `/api/dispense/confirm` 绕过核查。每个确认使用一次性 `qsm_operation_id`，请求已发出但无法确认结果时记为 `RESULT_UNKNOWN` 且禁止自动重试。如需限制测试仓位，可设置 `REAL_DISPENSE_TEST_SLOT=1`；如需演示 dry-run，可临时设置 `DISPENSE_DRY_RUN=true`。

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

药品页自助取药不能直接调用 `/api/dispense/confirm`。真实测试必须先在 UI
完成已登记人物的面部或指纹确认，取得短时 assertion，再用当前药品响应中的
`review_fingerprint` 完成核查。测试前请确认柜门附近安全：

```bash
curl -X POST http://127.0.0.1:8000/api/manual-medication-access/assess \
  -H "Content-Type: application/json" \
  -d '{"request_id":"现场唯一核查编号","medicine_id":"当前药品ID","slot":"当前显示仓位","service_user_id":"已识别人物ID","verification_method":"face","verification_assertion_id":"刚签发的身份断言","expected_review_fingerprint":"当前审核指纹"}'

curl -X POST http://127.0.0.1:8000/api/manual-medication-access/confirm \
  -H "Content-Type: application/json" \
  -d '{"request_id":"现场唯一确认编号","safety_check_id":"上一步PASSED返回的check_id","confirmed_safety_notice":true}'
```

只有第一步明确返回 `PASSED` 才能执行第二步。`RESULT_UNKNOWN` 表示柜门结果
无法证明，必须现场核对，禁止换 request ID 自动重试。

## 验证

```bash
python -m compileall zykh_station_app/backend/app
cd zykh_station_app/frontend && npm run test:motion && npm run build
```

## 阶段计划

1. 首页闭环和新架构基线；
2. 药品页 + 取药确认流程；
3. 模型主导问询 + 本地硬性安全边界；
4. 记录页 + 同步队列；
5. QSM real/mock 双模式接入验证；
6. QSM 外设功能联调入口；
7. 真实设备联调与演示稳定化；
8. 真实外设接入与逐页截图验收。
