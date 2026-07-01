# QSM 主控版智药康护

`jetson_app/` 是新的 QSM 主控应用。它把原硬件板保留为外设设备网关，由 QSM 主控负责主数据库、业务流程、AI 问诊和 Chromium Kiosk 触屏 UI。

## 架构边界

- QSM 主控：FastAPI、SQLite、React/Vite、AI 问诊、药柜/档案/计划/记录主数据。
- 外设设备：继续运行 `zykh_app/server.pl`，只负责摄像头、麦克风、喇叭、MAX30102、GY-614、UART8 开仓等外设。
- 连接：QSM 主控通过 USB ADB 建立 `adb forward tcp:18080 tcp:8080`，再访问 `http://127.0.0.1:18080`。
- 数据：QSM 主控从空库初始化 23 仓结构，不导入外设设备旧测试数据。

## 目录

```text
jetson_app/
  backend/     FastAPI API、SQLite 主库、外设设备代理、AI 流式问诊
  frontend/    React/Vite 1280x720 触屏 UI
  scripts/     ADB 转发、后端启动、Chromium Kiosk、系统检查、自启动安装
  data/        QSM 本地数据库、AI Key、日志；真实内容不提交
```

## 首次安装

```bash
cd /home/jetson/Documents/zykh/Zykh-QSM
python3 -m venv jetson_app/backend/.venv
jetson_app/backend/.venv/bin/pip install -r jetson_app/backend/requirements.txt

cd jetson_app/frontend
npm install
npm run build
```

## 启动

先确认外设设备的 `zykh_app/server.pl` 正在端口 `8080` 运行，然后在 QSM 主控上执行：

```bash
cd /home/jetson/Documents/zykh/Zykh-QSM
sh jetson_app/scripts/setup_adb_forward.sh
sh jetson_app/scripts/start_qsm_app.sh
```

后端监听：

```text
http://127.0.0.1:8088/
http://127.0.0.1:8088/api/status
```

Kiosk：

```bash
sh jetson_app/scripts/start_kiosk.sh
```

比赛展示或触屏调试时，推荐使用 720p 包装脚本。它会先把当前显示输出切到 `1280x720`，退出 Chromium 后自动恢复原分辨率：

```bash
sh jetson_app/scripts/start_kiosk_720p.sh
```

可选环境变量：

```bash
QSM_KIOSK_OUTPUT=HDMI-0 QSM_KIOSK_MODE=1280x720 QSM_KIOSK_RATE=60 sh jetson_app/scripts/start_kiosk_720p.sh
```

演示数据不会随服务启动自动覆盖真实数据。如需比赛展示数据，可手动执行：

```bash
sh jetson_app/scripts/seed_demo_data.sh
```

该脚本会先备份当前 `data/zykh_qsm.db`，再写入张三档案、8 个库存药仓、3 条用药计划、最近体征和操作记录。

管理后台也提供演示模式入口：

```text
/admin -> 快捷操作 -> 开启演示模式
/admin -> 快捷操作 -> 清空演示数据
```

开发调 UI 时可以打开视觉规范预览页：

```text
http://127.0.0.1:8088/style-preview
```

该页集中展示按钮、表单、状态胶囊和颜色 token，不进入老人端 kiosk 主流程。

## API

- `GET /api/status`
- `GET/POST /api/profile`
- `GET/POST /api/medicines`
- `GET/POST /api/plans`
- `GET /api/records`
- `POST /api/dispense`
- `GET/POST /api/vitals`
- `POST /api/vitals/read_all`
- `GET /api/camera/stream`
- `POST /api/camera/capture`
- `POST /api/medicine/scan`
- `POST /api/ai/chat/stream`
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
PYTHONPATH=jetson_app/backend jetson_app/backend/.venv/bin/python -m pytest jetson_app/backend/tests

cd jetson_app/frontend
npm run build
```

硬件联动时再执行：

```bash
adb devices -l
adb forward tcp:18080 tcp:8080
curl http://127.0.0.1:18080/api/status
curl http://127.0.0.1:8088/api/status
```

不要把真实 `.env`、`data/zykh_qsm.db`、`data/ai-api-key.txt`、日志或用户隐私数据提交到 Git。
