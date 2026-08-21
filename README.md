# 智药康护（Zykh-QSM）

基于 QSM368ZP-WF 的村镇智慧用药服务终端。系统面向偏远社区康护站，提供用药提醒、AI 应急问询、药品辅助匹配、禁忌风险提示、值守员复核、取药控制和离线记录同步。

> **版本状态：** `v2.0.1` 是 v2 系列第二个正式版本。

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
  8080  摄像头、音频播放和三分类柜指示灯控制
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
- [板端—小程序同步契约](zykh_station_app/docs/miniprogram-sync-contract.md)
- [设备验收清单](zykh_station_app/docs/demo-checklist.md)
- [v2.0.1 发布说明](CHANGELOG.md)

## v2 分类柜边界

- SQLite 中原有的 `hardware_slot=1..23` 继续作为 23 项固定药品的本地兼容定位字段；小程序使用板端适配后的 canonical `medicineId`。两者都不表示 23 个独立柜门，也没有迁移成三个可远程控制的云端仓位。
- 本机通过独立目录把每个药品 ID 映射到 `cabinet_id=1..3`，药品页按“日常用药 / 外用护理 / 慢病处方”三个实体分类柜显示，数量为 9/8/6。
- QSM 通过 ST-LINK VCP `/dev/ttyACM0`、115200 8N1 文本协议发送 `CABINET 1|2|3`、`STATUS` 与 `OFF`。旧 `/dev/ttyS5`、9600 和 `slot/control_code` 开柜协议已停用。
- 用户点击一次“确认身份并点亮药柜”后，系统自动完成身份与用药风险核验；无冲突时自动点亮对应分类柜并进入“还有药吗”确认页，有冲突时进入原有拦截界面。用户自行打开亮灯柜门取药，确认页结束后系统自动发送 `OFF` 并复核三柜均熄灭。
- 药品页默认显示三个分类柜；切换到药品视图后可按真实成功取药次数从高到低排序。所有带编号的界面文案统一为“1/2/3号柜”，分类柜视图不再显示“几号分类柜指示灯”徽标。
- 双歧杆菌三联活菌肠溶胶囊（本地 S09）实体放在 3 号柜，Station 仍以稳定 `medicineId=slot-09-bifid-triple`、`storageBox=PRESCRIPTION` 发送它；板端快照始终保留完整 23 种药和 `DAILY/CARE/PRESCRIPTION = 9/8/6`，不会为迎合消费端删掉 S09。
- 本轮没有修改 `zykh_station_app/cloudbase/` 或外部 Zykh-Miniprogram 代码。板端出站适配负责本地 S03 蒙脱石/S13 布洛芬到小程序 canonical S13 蒙脱石/S03 布洛芬的转换；远程 `UPSERT_MEDICINE`、开柜和点灯均失败关闭。小程序 `origin/main@9dd43c7` 的家属药库固定为 22 种并主动隐藏 S09，因此它目前只能展示其识别的 `9/8/5`；S09 仍保留在板端及云端审计数据中，不会被 22 药 finalize 删除。
- 目标云端具备快照、显式库存和药库分类能力时，Station 可进入“药库限定模式”：只写不含人物信息的设备摘要和完整 23 药。只有人物代次/tombstone、membership、体征归属和安全事件能力也全部通过时，才会同步人物数据或拉取命令。

> 按本次确认的现场分类，S09 无需单设冷藏柜或 `COLD` 软件分类。该项目映射不是通用储存建议；更换实物批次或包装时仍须核对其标签与说明书。

## 数据与安全边界

- `QSM_MODE=real`、`DISPENSE_DRY_RUN=false` 和真实分类柜亮灯是部署默认值；自动化验证必须使用 mock 与 dry-run，避免触发外设。
- Wi-Fi 密码、AI API Key、设备密钥、SQLite 数据库、运行日志和人物影像只保存在本机，不提交到 Git。
- AI 不诊断、不开药、不生成处方。中、高、紧急风险必须由值守员复核，或联系医生、救援人员。
- 点亮分类柜前必须重新核验身份断言、药品事实、库存、有效期、禁忌、本地柜位映射和请求幂等状态。
- `/api/device/check` 会通过 QSM 只读 `STATUS` 实测分类柜控制器，并以 `cabinet_light_ok`、`cabinet_light_status`、`cabinet_light_cabinet_id` 区分三柜已熄灭、某柜仍亮或状态不可用；不能只依据启用配置判断就绪。
- v2.0.1 默认启用临时 4G 展示策略：后端不访问物理 4G 模块、ADB 或 tether，终端右上角显示“4G 已连接 / 信号良好”，并在响应中保留 `simulated=true` 供诊断。恢复真实 4G 前必须显式关闭该策略并启用 kiosk tether。

## 发布验证

```bash
bash zykh_station_app/scripts/verify_release.sh
```

该命令只运行不接触真实硬件的自动化检查。真实设备验收按 [`zykh_station_app/docs/demo-checklist.md`](zykh_station_app/docs/demo-checklist.md) 单独执行并记录结果。
