# QSM368ZP-WF 智药康护终端应用

`jetson_app/` 是“智药康护：基于 QSM368ZP-WF 的蜂窝联网 AI 用药安全管家”的核心终端应用。第一版默认主场景是“偏远社区康护站 / 村镇智慧用药服务点”，同时保留老人、慢病和家庭用药安全作为基础场景。

系统不做 AI 诊断、不开药、不生成处方。AI 只用于应急辅助问询、药品辅助匹配、风险提示和用药安全核验。中/高/紧急风险必须管理员复核，或提示联系医生、村医、卫生院或救援人员。

## 架构边界

- QSM368ZP-WF 核心终端平台：FastAPI、SQLite、React/Vite 1280x720 Kiosk、站点配置、AI 应急问询、库存和记录主数据。
- 外设采集与执行控制平台：继续运行 `zykh_app/server.pl`，负责摄像头、麦克风、喇叭、MAX30102、GY-614、UART8 出药机构等硬件。
- 连接：核心终端通过 USB ADB 建立 `adb forward tcp:18080 tcp:8080`，访问 `http://127.0.0.1:18080`。
- 数据：核心终端维护本地 SQLite 主库；真实数据库、API Key、日志和隐私数据不提交。

## 双主线功能

- 今日用药提醒：承接老人、慢病、家庭用药计划、服药确认、漏服追踪和重复服药拦截。
- AI 应急问询：面向偏远社区、村镇弱网、临时服务点等场景，采集症状/语音/体征，匹配本地库存，输出风险提示和安全核验。

默认站点：

```text
偏远社区康护站 / 村镇智慧用药服务点
网络模式：弱网
AI 模式：本地AI，云端不可用时自动切 rules 兜底
同步方式：本地记录 + 待同步状态 + 模拟同步
```

## 本地 AI

第一版只接入本地 AI 配置，不安装 Ollama，也不下载模型。推荐配置：

```bash
LOCAL_AI_PROVIDER=ollama
LOCAL_AI_BASE_URL=http://127.0.0.1:11434
LOCAL_AI_MODEL=qwen2.5:1.5b
```

支持 provider：

```text
ollama | llamacpp | mock | rules
```

推荐模型：

```text
Qwen2.5 1.5B / 3B 量化版
Qwen3 1.7B / 4B 量化版
Llama 3.2 3B
Gemma 3 1B / 4B
```

当 Ollama、本地模型或云端 AI 不可用、超时或异常时，系统自动切换到 `rules`，保证离线演示仍可完成风险等级、候选类别、库存匹配、禁忌提醒和安全声明。

## 出药保护

默认：

```bash
DISPENSE_DRY_RUN=true
```

此时 `/api/dispense` 只做校验和记录，不真实调用外设出药机构。真实演示前必须现场确认安全条件，并手动设置：

```bash
DISPENSE_DRY_RUN=false
```

## 摄像头用途

扫码/拍照识别不只用于药品建档，还预留以下用途：

- 药品条码/二维码识别；
- 药盒/药板拍照确认；
- 站点码、维护码扫描；
- 出药后二次拍照复核，降低拿错药风险；
- 高风险事件拍照留存，方便管理员或远程人员复核；
- 设备内部药仓状态拍摄，辅助维护。

## 安装与启动

```bash
cd /home/jetson/Documents/zykh/Zykh-QSM
python3 -m venv jetson_app/backend/.venv
jetson_app/backend/.venv/bin/pip install -r jetson_app/backend/requirements.txt

cd jetson_app/frontend
npm install
npm run build
```

启动前确认外设采集与执行控制平台的 `zykh_app/server.pl` 正在端口 `8080` 运行，然后执行：

```bash
cd /home/jetson/Documents/zykh/Zykh-QSM
sh jetson_app/scripts/setup_adb_forward.sh
sh jetson_app/scripts/start_qsm_app.sh
```

访问：

```text
http://127.0.0.1:8088/
http://127.0.0.1:8088/terminal
http://127.0.0.1:8088/triage
http://127.0.0.1:8088/admin
```

Kiosk：

```bash
sh jetson_app/scripts/start_kiosk.sh
sh jetson_app/scripts/start_kiosk_720p.sh
```

演示数据：

```bash
sh jetson_app/scripts/seed_demo_data.sh
```

## API 摘要

- `GET /api/status`
- `GET/POST /api/site`
- `GET/POST /api/profile`
- `GET/POST /api/medicines`
- `GET/POST /api/plans`
- `POST /api/emergency/session`
- `POST /api/ai/triage/stream`
- `POST /api/local-ai/chat/stream`
- `POST /api/dispense`
- `GET /api/admin/logs`
- `POST /api/sync/mock`
- `POST /api/vitals/read_all`
- `GET /api/camera/stream`
- `POST /api/camera/capture`
- `POST /api/medicine/scan`
- `POST /api/audio/asr`
- `POST /api/audio/speak`
- `GET /api/settings`
- `POST /api/settings/ai_key`
- `POST /api/admin/reset`
- `POST /api/demo/seed`
- `POST /api/demo/clear`

## 验证

```bash
cd /home/jetson/Documents/zykh/Zykh-QSM
python3 -m py_compile jetson_app/backend/app/*.py
PYTHONPATH=jetson_app/backend jetson_app/backend/.venv/bin/python -m pytest jetson_app/backend/tests

cd jetson_app/frontend
npm run build
```

硬件联动检查：

```bash
adb devices -l
adb forward tcp:18080 tcp:8080
curl http://127.0.0.1:18080/api/status
curl http://127.0.0.1:8088/api/status
```

不要把真实 `.env`、`data/zykh_qsm.db`、`data/ai-api-key.txt`、日志或用户隐私数据提交到 Git。
