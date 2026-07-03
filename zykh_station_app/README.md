# zykh_station_app

`zykh_station_app` 是“智药康护”本机主应用。本机负责现代化界面、业务编排、本地数据、规则兜底和取药确认；QSM368ZP-WF 作为外设采集与执行控制网关，通过本机转发端口接入。

旧目录 `jetson_app/` 和 `zykh_app/` 只作为只读参考。新项目不依赖、不导入、不写入旧目录。

## 已完成范围

- 本机 FastAPI 后端骨架；
- SQLite 连接和初始化框架；
- QSM real/mock 双模式客户端，默认 real；
- 首页、药品页、问询页、记录页；
- 药品页取药确认，默认调用真实外设网关并保留本地记录；
- AI应急问询、风险提示、药品信息匹配、禁忌核验；
- 本地记录聚合和待同步队列；
- QSM real/mock 接入验证接口。
- 体征读取、扫码识别、真实取药确认联调和外设能力展示入口。
- 真实设备联调检查脚本和终端内系统检查入口。

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
sh scripts/open_kiosk.sh
```

## 配置

默认配置见 `backend/.env.example`：

```text
QSM_MODE=real
QSM_BASE_URL=http://127.0.0.1:18080
QSM_TIMEOUT_SECONDS=20
LOCAL_CAMERA_MODE=real
LOCAL_CAMERA_DEVICE=auto
DISPENSE_DRY_RUN=true
ENABLE_REAL_DISPENSE=0
AI_MODE=auto
AI_API_BASE=https://api.deepseek.com/chat/completions
AI_MODEL=deepseek-v4-flash
```

real 模式用于本机访问外设网关。如果 real 模式不可用，后端返回结构化错误并让首页显示“暂不可用”，不会用假体征或假识别结果掩盖问题。`QSM_MODE=mock` 只保留为本地闭环检查选项。

当前硬件分工：摄像头由本机主应用直接检测和抓拍；体征、音频和药仓控制通过外设网关。`/api/qsm/camera/capture` 是现有业务流程的兼容入口，内部走本机摄像头服务，不依赖外设网关摄像头接口。

`LOCAL_CAMERA_MODE=real` 会检查 `LOCAL_CAMERA_DEVICE`，`auto` 会优先探测常见 FF Camera 设备和 `/dev/video*`。如需本地闭环检查，可手动设置 `LOCAL_CAMERA_MODE=mock`。

AI 云通道兼容 DeepSeek OpenAI-style Chat Completions。密钥只从环境变量或本机私有文件读取，例如：

```bash
export AI_API_KEY_FILE=/userdata/zykh_app/data/ai-api-key.txt
```

无网或未配置密钥时，问询接口标记为“本地兜底”，使用现有 rules 逻辑，不假装离线大模型已经完成。

## QSM real 模式验证

外设网关可通过本机端口转发暴露到 `http://127.0.0.1:18080`：

```bash
cd zykh_station_app
sh scripts/adb_forward.sh
```

转发成功后启动后端：

```bash
QSM_MODE=real QSM_BASE_URL=http://127.0.0.1:18080 sh scripts/start_backend.sh
```

默认 `DISPENSE_DRY_RUN=true`，取药确认只写入 dry-run 记录。真实取药必须同时满足 `DISPENSE_DRY_RUN=false`、`ENABLE_REAL_DISPENSE=1`、`REAL_DISPENSE_TEST_SLOT` 已配置，并且请求体显式 `confirm_real_dispense=true`。

## 演示前检查

启动后端后可以执行：

```bash
cd zykh_station_app
sh scripts/check_devices.sh
curl http://127.0.0.1:8000/api/device/check
```

前端右上角有“系统检查”入口，显示当前模式、外设网关连接、本机摄像头、体征模块、出药联动和同步状态。普通终端 UI 不显示开发连接细节。

## 真实硬件 smoke

不会触发真实取药的接口：

```bash
curl http://127.0.0.1:8000/api/qsm/status
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

真实取药确认会调用外设网关。测试前必须确认安全仓位并开启双开关：

```bash
export DISPENSE_DRY_RUN=false
export ENABLE_REAL_DISPENSE=1
export REAL_DISPENSE_TEST_SLOT=1
curl -X POST http://127.0.0.1:8000/api/dispense/confirm \
  -H "Content-Type: application/json" \
  -d '{"medicine_id":"aspirin-enteric","slot":"A01","quantity":1,"reason":"真实联调确认","confirmed_safety_notice":true,"confirm_real_dispense":true}'
```

## 验证

```bash
python -m compileall zykh_station_app/backend/app
cd zykh_station_app/frontend && npm run build
```

## 阶段计划

1. 首页闭环和新架构基线；
2. 药品页 + 取药确认 dry-run；
3. 问询页 + AI rules 兜底；
4. 记录页 + 同步队列；
5. QSM real/mock 双模式接入验证；
6. QSM 外设功能联调入口；
7. 真实设备联调与演示稳定化；
8. 真实外设接入与逐页截图验收。
