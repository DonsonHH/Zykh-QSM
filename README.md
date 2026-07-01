# Zykh-QSM

智药康护 QSM368ZP-WF / RK3568 本地终端项目。

本仓库包含：

- `zykh_app/`：板端 Perl 后端、Go 原生 HDMI UI、Web 调试页、启动脚本
- `jetson_app/`：QSM 主控版 FastAPI 后端、React/Vite Kiosk UI、SQLite 主库、外设设备 ADB 网关代理
- `智药康护-QSM368ZP-WF-项目调试记录.md`：项目调试记录和部署说明

敏感信息不写入仓库。Wi-Fi 密码、AI API Key 等请在板端通过环境变量或 `/userdata` 下的本地文件配置。

当前推荐的新部署形态（展示和文档中主机统一称为 QSM，连接的硬件板称为外设设备）：

```text
QSM 主控终端
  127.0.0.1:8088  FastAPI + React Kiosk + SQLite 主库
  127.0.0.1:18080 adb forward 到外设设备 /api/*

外设设备
  127.0.0.1:8080  zykh_app/server.pl 硬件网关
```
