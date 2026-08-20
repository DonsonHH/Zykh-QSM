# 板端—小程序 3.0 同步适配契约

## 状态与变更边界

本轮 Station 对接目标是 Zykh-Miniprogram 的 CloudBase schema revision
`3.0-three-box-library`，药库能力为 `medicineStorageBoxes=v1`。本轮只修改
Zykh-QSM 的板端传输适配和本地实体柜目录：

- 不修改或部署 `zykh_station_app/cloudbase/**`；
- 不修改或发布 Zykh-Miniprogram 仓库；
- 不把小程序 `storageBox` 当作 QSM 实体柜编号；
- 不开放远程开柜、远程点灯或自动出药。

发布前必须只读记录线上 `PING`、小程序 commit 和 QSM commit。若线上 revision
或能力与本契约不一致，停止 Station 同步适配上线，不得临时改 CloudBase 或小程序
绕过差异。

## 实体分类柜：9/8/6

`S01..S23` 是 Station 本地 `hardware_slot` 兼容编号，不是 23 个柜门。QSM
实体柜只使用 `cabinet_id=1..3`：

| 实体柜 | 本地标签 | Station 本地编号 | 数量 |
| --- | --- | --- | --- |
| 1 | 日常用药 | S01、S03、S05、S07、S08、S11、S12、S13、S23 | 9 |
| 2 | 外用护理 | S10、S15、S16、S17、S18、S19、S20、S22 | 8 |
| 3 | 慢病处方储备 | S02、S04、S06、S09、S14、S21 | 6 |

实体 3 号柜包含 S09 双歧杆菌三联活菌肠溶胶囊。这是现场摆放与 QSM
`CABINET 3` 亮灯的权威映射；实体柜目录只由 `cabinet_v2_catalog.py` 维护。
该软件映射不替代实物储存说明；若当前包装要求冷藏，现场不得放入普通柜，必须
暂停该项取药并重新确认映射。

## 小程序药库投影：9/8/5/1

小程序的 `storageBox` 是家庭药库显示分类，不是实体柜控制字段：

| `storageBox` | 小程序名称 | 小程序 canonical 兼容编号 | 数量 |
| --- | --- | --- | --- |
| `DAILY` | 日常高频内服 | 1、3、5、7、8、11、12、13、23 | 9 |
| `CARE` | 外用消毒护理 | 10、15、16、17、18、19、20、22 | 8 |
| `PRESCRIPTION` | 慢病处方储备 | 2、4、6、14、21 | 5 |
| `COLD` | 冷藏药品 | 9 | 1 |

因此 S09 虽然实体放在 3 号柜，上传时仍必须是 `storageBox=COLD`。小程序把它
单独显示为冷藏药品，不计入三个普通药柜；Station 不得根据 `COLD` 改变现场
`cabinet_id=3`，小程序也不能根据实体柜编号覆盖 `COLD`。

## Canonical 药品身份适配

Station 固定目录中 S03 是蒙脱石散、S13 是布洛芬缓释胶囊；小程序 canonical
目录中二者的兼容编号相反。板端传输适配必须执行下表转换：

| Station 本地身份 | 药品 | 小程序 canonical 身份 | 小程序兼容编号 | `storageBox` |
| --- | --- | --- | --- | --- |
| `slot-03-diosmectite` / S03 | 蒙脱石散 | `slot-13-montmorillonite` | 13 | `DAILY` |
| `slot-13-ibuprofen` / S13 | 布洛芬缓释胶囊 | `slot-03-ibuprofen` | 3 | `DAILY` |

其余 21 种固定药品的本地与小程序 `medicineId`、兼容编号一一相同。转换规则只由
`medicine_cloud_projection.py` 维护，并遵守以下约束：

- Station 快照的 `medicineId` / `medicine_id` 使用小程序 canonical 身份；
- `legacySlot`、`hardwareSlot`、`hardware_slot` 和 `slot` 使用小程序 canonical
  兼容编号，不能被解释为实体柜号；
- 小程序反向命令携带 canonical `medicineId` 或兼容编号时，Station 先解析为本地
  固定身份，再修改对应本地记录；
- 命令同时携带身份、兼容编号或 `storageBox` 时，任一字段互相冲突都失败关闭；
- 条码、追溯码、药名、标签和实体柜号都不能替代稳定药品身份；
- 未配置投影的药品不得猜测 `medicineId`、`storageBox` 或实体柜。

## 快照与余量事实

- 23 种固定药品每种只上传一条 canonical 行；`cabinet_id` 不上传。
- `inventoryState=STOCKED/DEPLETED/UNKNOWN` 是小程序余量事实。旧 `quantity` / `stock`
  只作为兼容字段，不能把未知余量静默解释为有药。
- 只有本机“已经用完”确认的请求 ID 与确认时间同时匹配持久化记录时，才上传
  `depletionConfirmedAt` 和
  `depletionConfirmationSource=ON_DEVICE_CONFIRMATION`。
- 真实亮灯和人工取药不会自动把库存减为零；“还有药”保持有药，“已经用完”
  才写入 `DEPLETED`。
- `storageBox` 是受版本控制的只读投影，反向药品命令不能修改它。

## 人物、安全事件与远程命令边界

Station 继续携带并复核人物代次、保持问询/体征发送侧 append-only，并使用既有
设备密钥；本轮不修改目标 CloudBase，因此 membership 行过滤、云端人物代次、
事件保留和通知收件人必须另行对实际部署验收，不能由板端测试或 `PING` 名称替代。
非自动出药的安全事件可继续使用
`dispenseStatus=NOT_APPLICABLE`。配对家属的最小命令仍只允许：

| 命令 | 用途 | 额外限制 |
| --- | --- | --- |
| `AUDIO_BEEP` | 终端蜂鸣提示 | 不开柜、不点亮药柜 |
| `AUDIO_SPEAK` | 语音提醒 | 指定人物时复核当前人物代次 |
| `READ_VITALS_ALL` | 发起体征读取 | 必须携带可核验人物，或明确使用允许的独立归属 |

`OPEN_CABINET`、`DISPENSE` 与其他物理执行命令继续失败关闭。CloudBase 或小程序
不能代替现场用户完成身份核验、风险核查、点灯、开柜、余量确认或熄灯。

## 验证顺序

### 1. 固定边界

1. 记录 QSM 与 Zykh-Miniprogram 的当前 commit，并保存线上 `PING` 完整响应。
2. 确认本轮 QSM diff 对 `zykh_station_app/cloudbase/**` 为零，小程序工作树干净。
3. 备份 Station SQLite；本轮不创建、迁移、删除或部署 CloudBase 数据与函数。

### 2. 板端自动化

在 QSM 仓库根目录运行：

```bash
(cd zykh_station_app/backend && \
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q \
    tests/test_cabinet_v2_catalog.py \
    tests/test_medicine_cloud_projection.py \
    tests/test_cloud_sync_service.py)
```

测试必须证明：

- 23 种药品在实体柜中恰好出现一次，数量为 9/8/6；
- 云投影中恰好出现一次，数量为 9/8/5/1；
- S09 实体为柜 3、云投影为 `COLD`；
- S03/S13 快照和反向命令都按 canonical 身份正确转换；
- 冲突身份、编号或 `storageBox` 失败关闭。

### 3. 只读联调

1. 线上 `PING` 应为目标 `schemaRevision=3.0-three-box-library`，并包含
   `medicineStorageBoxes=v1`；不满足时停止，不部署 QSM 仓库中的 CloudBase。
2. 用 fake adapter 检查完整快照为 `DAILY=9`、`CARE=8`、
   `PRESCRIPTION=5`、`COLD=1`，且没有 `cabinet_id`。
3. 小程序药库应显示三个普通药柜 22 种药品和单独的 1 种冷藏药品；逐项核对
   S03 蒙脱石、S13 布洛芬和 S09 双歧杆菌。
4. 确认小程序不存在 23 仓、远程开柜、远程点灯、自动出药或替用户确认余量的入口。

### 4. 现场取药

1. 本地药品页显示“日常用药 / 外用护理 / 慢病处方储备”，数量为 9/8/6。
2. 用户只点击一次“确认身份并点亮药柜”；有冲突时进入原有拦截界面且 QSM
   调用数为零，无冲突时自动点亮正确实体柜并进入“还有药吗”确认页。
3. 用户自行打开亮灯柜门取药。“还有药吗”页面结束后系统自动发送 `OFF`，并以
   `STATUS OFF` 复核三柜熄灭；不得要求用户再次点击点灯或熄灯。

## 回滚原则

本轮没有修改 CloudBase 或小程序，因此代码回滚只回滚 Station 适配与本地实体柜
目录。若已产生真实余量或安全事件，先停止同步并保留 SQLite、CloudBase 导出与日志，
不得把程序回滚扩展为删除业务数据。实体映射验收失败时停止现场取药；云投影验收失败
时停止同步，二者都不得通过改 `storageBox`、药名或旧编号绕过目录。
