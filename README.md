# 智药康护（Zykh-QSM）

基于 QSM368ZP-WF 的村镇智慧用药服务终端。系统面向偏远社区康护站，提供用药提醒、AI 应急问询、药品辅助匹配、禁忌风险提示、值守员复核、取药控制和离线记录同步。

> **版本状态：** `v1.9.0` 是 v1 系列最终版。后续功能开发从 v2 系列继续。

## 仓库结构

| 路径 | 用途 | 发布状态 |
| --- | --- | --- |
| `zykh_station_app/` | FastAPI、React/Vite Kiosk、SQLite、CloudBase 同步和 QSM 适配器 | 当前主应用 |
| `zykh_app/` | 板端 Perl/Go 网关与硬件维护工具 | 兼容参考，主应用不依赖其源码 |
| `CONTEXT.md` | 产品领域语言与术语边界 | 文档 |
| `CHANGELOG.md` | 版本变更记录 | 文档 |

源文件、本机运行数据和可安全清理的生成物说明见 [`zykh_station_app/docs/repository-files.md`](zykh_station_app/docs/repository-files.md)。

## 快速启动

```bash
cd zykh_station_app
python -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
sh scripts/start_all.sh
```

终端页面默认地址：<http://127.0.0.1:5173>。

完整部署、配置和设备联调步骤见 [`zykh_station_app/README.md`](zykh_station_app/README.md)。

## 运行拓扑

```text
本机
  127.0.0.1:8000   FastAPI + SQLite
  127.0.0.1:5173   React/Vite Kiosk
  127.0.0.1:18080  QSM 主外设网关
  127.0.0.1:18081  QSM 人脸识别网关
  127.0.0.1:18082  QSM 麦克风采集网关
  127.0.0.1:18084  QSM 离线语音识别
  127.0.0.1:18085  QSM 体征会话网关
  127.0.0.1:18086  QSM 指纹网关

QSM368ZP-WF
  8080  摄像头、音频播放和药柜控制
  8081  人脸特征提取与匹配
  8082  FF Camera 麦克风 PCM 采集
  6006  Paraformer 离线语音识别
  8085  UART8 综合体征采集
  8086  AS608 指纹识别
```

## 文档入口

- [主应用运行与配置](zykh_station_app/README.md)
- [系统架构](zykh_station_app/docs/architecture.md)
- [API 契约](zykh_station_app/docs/api.md)
- [QSM 集成](zykh_station_app/docs/qsm-integration.md)
- [CloudBase 同步](zykh_station_app/docs/cloudbase-sync.md)
- [设备验收清单](zykh_station_app/docs/demo-checklist.md)
- [v1.9.0 发布说明](CHANGELOG.md)

## 数据与安全边界

- `QSM_MODE=real`、`DISPENSE_DRY_RUN=false` 和真实开柜是部署默认值；自动化验证必须使用 mock 与 dry-run，避免触发外设。
- Wi-Fi 密码、AI API Key、设备密钥、SQLite 数据库、运行日志和人物影像只保存在本机，不提交到 Git。
- AI 不诊断、不开药、不生成处方。中、高、紧急风险必须由值守员复核，或联系医生、救援人员。
- 开柜前必须重新核验身份断言、药品事实、库存、有效期、禁忌和请求幂等状态。

## 发布验证

```bash
bash zykh_station_app/scripts/verify_release.sh
```

该命令只运行不接触真实硬件的自动化检查。真实设备验收按 [`zykh_station_app/docs/demo-checklist.md`](zykh_station_app/docs/demo-checklist.md) 单独执行并记录结果。
