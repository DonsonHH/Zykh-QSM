# CloudBase 与微信小程序同步

## 当前链路

主机 FastAPI 是终端数据的主同步代理：

```text
SQLite / QSM 外设
  -> FastAPI CloudSyncWorker（2 秒周期）
  -> CloudBase HTTP 云函数 api
  -> devices / medicines / vitals / records / commands
  -> 微信小程序
```

## 3.0 小程序投影与实体柜边界

本轮只适配 Station 到现有 Zykh-Miniprogram 3.0 药库契约，不修改或部署
`zykh_station_app/cloudbase/**`，也不修改小程序代码。Station 本地稳定
`Medicine.id` 与小程序 canonical `medicineId` 由
`medicine_cloud_projection.py` 转换；溯源码、条码、药名、标签和实体柜号都不是
药品身份。

QSM 实体柜使用独立的 9/8/6 映射：

| QSM 实体柜 | 本地标签 | Station 本地编号 | 数量 |
| --- | --- | --- | --- |
| 1 | 日常用药 | S01、S03、S05、S07、S08、S11、S12、S13、S23 | 9 |
| 2 | 外用护理 | S10、S15、S16、S17、S18、S19、S20、S22 | 8 |
| 3 | 慢病处方储备 | S02、S04、S06、S09、S14、S21 | 6 |

小程序 `storageBox` 使用另一套 9/8/5/1 只读投影：

| `storageBox` | 小程序名称 | canonical 兼容编号 | 数量 |
| --- | --- | --- | --- |
| `DAILY` | 日常高频内服 | 1、3、5、7、8、11、12、13、23 | 9 |
| `CARE` | 外用消毒护理 | 10、15、16、17、18、19、20、22 | 8 |
| `PRESCRIPTION` | 慢病处方储备 | 2、4、6、14、21 | 5 |
| `COLD` | 冷藏药品 | 9 | 1 |

S09 双歧杆菌实体放在 3 号柜，但对外仍为 `storageBox=COLD`。本地 S03
蒙脱石散上传为小程序 canonical `slot-13-montmorillonite` / 兼容编号 13；
本地 S13 布洛芬上传为 `slot-03-ibuprofen` / 兼容编号 3。反向命令执行相反
转换，身份、编号或 `storageBox` 冲突时失败关闭。

S09 的软件映射不是药品储存条件判定。现场必须核对当前实物包装；若要求冷藏，
不得按该映射放入普通柜，应暂停该项现场取药并重新确认摆放方案。

`cabinet_id` 永不上传，也不能从 `storageBox` 反推。目标 CloudBase 探针为
`schemaRevision=3.0-three-box-library`、`medicineStorageBoxes=v1`；探针不匹配时
停止 Station 上线，不得在本轮临时修改或部署 CloudBase。完整契约见
[`miniprogram-sync-contract.md`](miniprogram-sync-contract.md)。

云端仍无开柜或远程亮灯命令。历史 `OPEN_CABINET` 继续失败关闭，
不会到达 QSM；药柜灯只能由本地安全核查通过后的现场流程点亮。

小程序允许的反向操作通过 `commands` 集合完成。主机拉取命令并将其置为 `running`，执行后 ACK 为 `done` 或 `failed`。`cloud_command_history` 保存本地执行结果，同一命令 ID 即使重复下发也不会重复执行。远程开柜不属于允许动作；历史 `OPEN_CABINET` 命令会被改写为失败且不会调用 QSM。

## 已同步数据

- 设备在线状态和同步代理版本；
- 23 项药品的小程序 canonical `medicineId`、兼容编号、只读 `storageBox` 及药品信息，包括规格、追溯码、库存、低库存线和原始有效期精度；
- 服务对象；
- 今日计划；
- 体征记录；
- AI 问询记录；
- 站点取药记录。
- 人物—药品安全核查及物理结果（独立 append-only 事件，不属于快照）。

人物同步不是普通的“当前列表”覆盖：Station 会把活动人物和归档 tombstone 一起
写入 `service_users`。每行都必须有稳定 `persona_generation`；文档键由
`deviceId + personId + generation digest` 组成。同一人物 ID 的不同代次不会互相
覆盖。`GET_SNAPSHOT` 与 `GET_DEVICE.syncSummary` 只公开未归档人物，但 tombstone
保留在云存储中用于隔离历史所有权。
计划和取药记录也携带生成时的 `persona_generation`；问询、体征和安全事件沿用
各自持久化的人物代次。带 generation map 的 membership 只可读取代次完全一致
的行，缺失或不一致的旧行均失败关闭，不会因为复用相同 person ID 泄露给新人物。
问询、体征和用药安全事件在 Station 发送侧仍按 append-only 处理：板端不对问询
或体征请求 finalize，安全事件不参与快照 finalize。本轮没有修改或部署目标 3.0
CloudBase，所以这些本地证据不能证明云端读取、人物代次或保留策略；上线前必须对
实际部署独立验收，不能仅凭 `PING` 能力名称推定实现安全。

本版本不再向旧版云函数降级。每个同步周期会先执行只读 `PING`；只有
`schemaVersion=2`、`schemaRevision=3.0-three-box-library` 且
`capabilities.medicineStorageBoxes=v1` 同时成立时，才允许发布配对码、拉取命令、
上传快照或发送安全事件。任一条件不匹配都会在发生云端写入或执行云端命令前失败关闭，
避免旧仓位语义把 S03/S13 更新到错误药品。

## CloudBase 基线：本轮不部署

本轮发布边界是“适配现有 CloudBase/小程序，更新 Station”，不是云函数迁移。
禁止从本仓库运行 `tcb` 部署、`deploy_cloudbase_sync.sh`、集合创建或数据清理，
也禁止把 `zykh_station_app/cloudbase/` 复制到小程序工程覆盖现有实现。

上线前只做以下只读检查：

1. 保存线上 `PING` 完整响应，确认目标为
   `schemaRevision=3.0-three-box-library` 且
   `capabilities.medicineStorageBoxes=v1`；
2. 对比发布基线，确认 `zykh_station_app/cloudbase/**` 没有本轮 diff；
3. 确认 Zykh-Miniprogram 工作树、commit 和已发布版本未被本轮修改；
4. 使用 fake adapter 验证板端快照和反向命令，不向真实集合写测试数据。

revision、能力、人物代次、membership、append-only 或命令权限任一不匹配时，
停止 Station 上线并保留快照，不得靠部署 QSM 仓库里的旧云函数“修复”。板端适配
通过后，真实全量同步仍须按既有运维流程先备份再执行；不得手工删除 ownerless、
其他所有者或真实业务文档。验证与回滚顺序见
[`miniprogram-sync-contract.md`](miniprogram-sync-contract.md)。

## 小程序反向命令

可将 `cloudbase/miniprogram/remoteCommands.js` 放入小程序工具目录。它使用云函数 `CREATE_COMMAND`，避免页面直接拼装命令结构。

`cloudbase/miniprogram/stationSync.js` 提供 `loadStationSnapshot()` 和页面按需使用的 `subscribeStationSnapshot()`。订阅以 5 秒周期调用经过 membership 校验的云函数；不再按可输入的 `deviceId` 直接 watch 健康集合，避免原始变更在授权投影前下发客户端。v2 下读取独立集合，v1 下自动从设备 `syncSummary` 和原有集合组合数据。2 秒设备心跳中的 `syncSummary.recentInquiries` 只携带摘要字段和 `messageCount`，不携带完整 `messages`，且 `GET_DEVICE` 会按当前家属人物范围裁剪摘要。`LIST_INQUIRIES` 同样只返回摘要，完整且最多 80 条的消息明细仅由 `GET_INQUIRY_DETAIL` 返回。`GET_SNAPSHOT` 完整分页读取人物集合后返回 `serviceUsersSnapshotComplete=true`；兼容回退也保留 Station 心跳中的同名可信标记。页面在 `onShow` 中建立订阅，并在 `onHide`/`onUnload` 中调用返回的停止函数。

`remoteCommands.js` 只调用 v2 的 `CREATE_COMMAND`。云函数缺少该 action 时会
明确提示升级，不会降级为小程序直接写入 `commands` 集合；网络超时、权限拒绝、
命令类型或字段校验失败同样原样返回失败。helper 在本地也拒绝
`OPEN_CABINET`，通用命令入口不能绕过 membership、允许列表或请求摘要校验。

`CREATE_COMMAND` 只接受微信小程序通过 `wx.cloud.callFunction` 发起的 Event
调用。公共 HTTP `/api` 即使携带相同 action 也会被拒绝，防止外部请求
伪造设备命令。ACTIVE membership 是所有健康数据读取的前置条件；人物范围
受限的家属只能看到对应人物的计划、问询、记录、体征和人物卡，越权详情统一
返回未找到。`GET_INQUIRY_DETAIL` 与列表使用同一人物范围。

ACTIVE 只表示 membership 当前有效，不会自动授予所有读取能力。单项读取还会
校验对应权限：药品为 `READ_MEDICINE`，体征为 `READ_VITALS`，取药记录为
`READ_RECORD`，问询列表与详情为 `READ_INQUIRY`，人物卡为 `READ_PROFILE`，
计划为 `READ_PLAN`；安全事件继续使用 `READ_SAFETY`，命令列表与写命令均要求
`CREATE_COMMAND`。`GET_SNAPSHOT` 和 `GET_DEVICE.syncSummary` 只返回当前
membership 已授权且人物范围匹配的分区；权限数组为空时不返回任何健康分区或
健康计数。
配对签发的 `CAREGIVER` 会员具有最小 `CREATE_COMMAND` 权限，但服务端还会按
角色二次收窄：只允许 `AUDIO_BEEP`、`AUDIO_SPEAK` 和
`READ_VITALS_ALL`。家属不能借该权限下发 `AI_CHAT`、药品/人物/计划写入、
`OPEN_CABINET` 或任何未列出命令。

同一 `CREATE_COMMAND.requestId` 在事务中绑定规范化请求摘要：相同内容安全重放，
不同内容返回 `IDEMPOTENCY_CONFLICT`，并发请求也不能互相覆盖。缺少
`CREATE_COMMAND` 权限的 membership 不能下发命令，具备该权限也仍受上述角色允许列表限制。
人物命令执行前还会从当前唯一活动人物行重验 membership 绑定的代次，
并由服务端把该代次写入命令；旧代次授权不能向同 ID 的新人物发送提醒、
读取体征、发送问询或更新资料/计划。无人物归属的通用语音设备测试可不携带代次；
一旦 `AUDIO_SPEAK` 指定人物，云端和 Station 都会复核当前 `persona_generation`。

远程 `READ_VITALS_ALL` 必须携带可核验的服务对象身份，或显式声明
`attribution_source=STANDALONE`；空身份、空归属请求会失败关闭。人物归属命令由
服务端固化当前 `persona_generation`。Station 在读取外设前再次核对当前人物代次，
并只落一条带可信姓名、代次及归属来源的本地体征记录，不再额外生成未登记副本。
板端 ACK 成功后，云函数把测量结果镜像到
`vitals`，保留人物、代次、问询会话、归属来源和源命令 ID；可选镜像失败不会
反向破坏命令 ACK。

## 微信设备绑定

可将 `cloudbase/miniprogram/deviceMemberships.js` 嵌入实际小程序。它只通过
`wx.cloud.callFunction` 提供 `GET_MY_DEVICES`、
`REDEEM_DEVICE_PAIRING_CODE` 和能力检查，不读取或写入云数据库，也不会用本地
缓存的 `deviceId` 授权。两项绑定 action 只接受带当前微信 `OPENID` 的 Event
调用，公共 HTTP 调用失败关闭。

`device_pairing_codes` 是服务端专用集合。Station 受保护管理台的“家属配对”
区域会为选定的活动服务对象生成 256-bit CSPRNG 一次性原文；原文只在当前
页面显示至过期，管理员审计只记录授权对象与 TTL。Station 只把 SHA-256、
人物范围、每个人物的期望 `persona_generation` 和 5–15 分钟 TTL 通过设备认证
通道交给云端，文档 ID 为
`pairing-<sha256(raw_code)>`，字段包含同一 `codeHash`、`deviceId`、`role`、
`permissions`、`service_user_scopes`、`service_user_generations`、
`status=UNUSED` 和带时区的 `expiresAt`；
不得保存原文。兑换请求只提交 `pairingCode`，云函数忽略调用者伪造的设备、角色
或权限，并在一个事务中重新校验哈希、未使用状态和过期时间，创建 ACTIVE
membership 后把码置为 `CONSUMED`。重复、过期、未知、已绑定或并发败方统一
返回 `PAIRING_CODE_INVALID`；`GET_MY_DEVICES` 只枚举当前 OPENID 的 ACTIVE
membership。

云端以当前唯一未归档人物行解析并复核代次；Station 提交的期望代次陈旧、同一
ID 同时存在多个活动代次、人物已归档或 canonical 文档缺失时均拒绝签发。新版
pairing/membership 会保存 generation map；以后同一人物 ID 启用新代次时，旧
membership 不会自动获得新人物卡、计划、记录、问询、体征、安全事件或命令权限。
安全事件通知收件人在写回执和 outbox 的事务中也会复核事件代次。为保证云先部署，旧 pairing 文档与旧
membership 仍可完成原兼容流程，但重新签发后即进入代次绑定契约。

签发 action 只接受当前 `deviceId` 在服务端 `DEVICE_SECRETS` 中配置的独立密钥；
共享 `DEVICE_SECRET` 不能签发配对码。外部 Windows 小程序工程的扫码/输入和设备
切换页面仍不在本仓。上线前还需把 `device_pairing_codes` 与
`device_memberships` 的数据库规则设为小程序端不可直读写，并在实际小程序接入
helper 后完成双人并发、过期、撤销与跨设备验收；本轮不会创建真实配对码或部署
云函数。

同步与命令兼容契约可在主机执行：

```bash
node zykh_station_app/cloudbase/miniprogram/test-sync-contract.cjs
```

云端总命令允许列表为：

```text
AUDIO_BEEP
AUDIO_SPEAK
READ_VITALS_ALL
AI_CHAT
UPSERT_MEDICINE
UPSERT_SERVICE_USER
UPSERT_TODAY_PLAN
```

其中通过家属配对签发的 `CAREGIVER` 只能使用前三项；其余命令仅在更高
权限角色同时通过其它字段、人物代次和设备权限校验时可用。

旧版反向 `UPSERT_MEDICINE` 命令继续接受 `hardware_slot`（兼容
`hardwareSlot` / `slot`），但该值属于小程序 canonical 兼容编号；Station 必须先经
板端投影解析为本地记录，尤其不能直接把小程序 S03/S13 当成本地 S03/S13。
快照使用小程序 canonical `medicineId`，两条路径都不以条码去重，也不接受本地
物理 `cabinet_id` 或 `storageBox` 作为药品身份替代键。`storageBox` 是 Station
快照中受信的小程序药库投影，不属于反向命令可修改字段。局部修改
使用嵌套补丁：

```json
{
  "operation": "patch",
  "hardware_slot": 13,
  "patch": {
    "name": "布洛芬缓释胶囊",
    "spec": "0.3克×10粒",
    "traceCode": "TRACE-EXAMPLE",
    "quantity": 0,
    "lowStockLine": 2,
    "expireDate": "2029-01",
    "expiryPrecision": "month"
  }
}
```

小程序可以上传待审核的安全资料草稿：`aliases`、`active_ingredients`、
`structured_contraindications`，并可显式携带
`safety_review_status: "draft"`。终端会清空草稿的审核人和审核时间，且草稿不会进入
AI 问询候选池。小程序不能把资料标记为 `reviewed`，也不能提交
`safety_reviewed_by` 或 `safety_reviewed_at`；这些审核动作只允许在受控本地流程完成。
药师组合白名单和成分冲突矩阵同样不接受小程序远程写入。

若补丁同时更换药品身份，终端会清空未在该补丁中提供的旧安全资料，但保留同一补丁
显式携带的三类新草稿字段。空仓 `upsert` 也会在创建药品后保存同一 payload 的草稿，
并保持 `package_verified=false` 与 `safety_review_status=draft`。

终端只修改 `patch` 中明确出现的字段，库存和低库存线允许为 `0`。
快照以小程序 canonical `medicineId` 作身份，列表仍可按 canonical 兼容 `slot`
排序；本地 1–3 实体柜映射不会进入快照，只有独立的 `storageBox` /
`storage_box` 小程序药库投影会上传。实体 `cabinet_id` 不上传，反向药品命令也
不能修改实体柜或药库投影。命令字段到 SQLite 与快照字段的对应关系为：

| 命令字段 | SQLite | 小程序快照字段 |
| --- | --- | --- |
| `hardware_slot` / `hardwareSlot` / `slot` | `hardware_slot` | `slot`, `hardwareSlot` |
| `spec` | `spec` | `spec` |
| `traceCode` / `trace_code` | `trace_code` | `traceCode`, `trace_code` |
| `quantity` / `stock` | `stock` | `quantity`, `stock` |
| `lowStockLine` / `low_stock_line` | `low_stock_line` | `lowStockLine`, `low_stock_line` |
| `aliases` | `aliases_json`（草稿） | `aliases` |
| `active_ingredients` | `active_ingredients_json`（草稿） | `active_ingredients` |
| `structured_contraindications` | `structured_contraindications_json`（草稿） | `structured_contraindications` |
| `safety_review_status` | 远程只允许 `draft` | `safety_review_status` |
| `expireDate` / `expire_date` | `expire_date` | `expireDate`, `expire_date`, `expiryPrecision` |

`expireDate` 原样保留 `YYYY-MM` 或 `YYYY-MM-DD`；`expiryPrecision` 由终端据此生成为 `month` 或 `day`。命令中若同时携带 `expiryPrecision`，云函数会先校验它与日期格式一致。

## 家属安全事件只读接口

Station 以 `medication-safety:{check_id}` 为稳定事件 ID：`BLOCKED` 与
`CHECK_FAILED` 在核查终态写入一条 outbox；`PASSED` 直到确认得到本地分类柜亮灯终态后，
才把核查与物理执行双轴合并写入同一条事件。为保持现有 CloudBase 契约，字段名和枚举不在本轮板端适配中破坏性迁移；事件同时携带人物 profile revision、
药品审核指纹与可用的 QSM operation ID。联网且云端声明
`medicationSafetyEvents=v1` 后，使用设备密钥调用
`REPORT_MEDICATION_SAFETY_EVENT`；同一 `event_id + payload_digest` 安全重放，
同 ID 不同摘要拒绝。事件永不加入 `FINALIZE_SNAPSHOT`。

小程序 helper `cloudbase/miniprogram/medicationSafetyEvents.js` 仅提供：

```text
LIST_MEDICATION_SAFETY_EVENTS
GET_MEDICATION_SAFETY_EVENT
MARK_MEDICATION_SAFETY_EVENT_READ
```

三者都要求 CloudBase `_openid` 对应 ACTIVE `device_memberships`、包含
`READ_SAFETY`，并遵守 `service_user_scopes`。越权详情统一返回未找到，列表
使用 `occurredAt + eventId` 稳定游标，单页最多 50 条；已读回执按家属独立、
事务幂等且保留首次 `readAt`。helper 不包含 REPORT、批准、解除、重试亮灯
或任何数据库直写后备路径。

每次 `REPORT_MEDICATION_SAFETY_EVENT` 成功落库后，云函数会为当时仍是
ACTIVE、具备 `READ_SAFETY` 且人物范围匹配的每个 OPENID，在事务中同时补齐
UNREAD receipt 和一条 `caregiver_notification_outbox`。出站项以
`deviceId + eventId + recipientOpenId` 的 SHA-256 稳定键幂等，初始状态为
`PENDING`，只含事件 ID、设备 ID、收件人、membership ID 和模板键，不含药名、
人物名、病史、禁忌或问询内容；事件重放不会重复排队。REPORT 返回不等待微信
订阅消息发送，推送失败也不能删除事件或把 receipt 标为 READ。

独立 `caregiverNotificationWorker` 以事务认领 `PENDING`，并在发送前重新验证原始
事件、ACTIVE membership、`READ_SAFETY`、人物范围、`AUTHORIZED` 订阅授权和
未读 receipt。发送内容固定为“家庭药箱新增一条取药核查记录 / 请打开小程序
查看”，不含姓名、药名、病史、原因或问询内容，因此既适用于正常取药记录，也
不会把正常结果误报成拦截。明确拒绝记为 `FAILED`；超时、异常或遗留 `SENDING`
只收敛为 `RESULT_UNKNOWN`，不自动重试；发送结果只更新 outbox 与 receipt 的通知
尝试状态，不修改安全事件、已读时间或任何 Station 命令。

部署脚本默认创建/更新 worker 但保持 timer 关闭。只有外部小程序已经通过
`wx.requestSubscribeMessage` 获取授权并安全写入
`caregiver_notification_subscriptions`、微信模板和真实页面已审核、CloudBase
OpenAPI 权限已确认时，才可显式启用：

```bash
CAREGIVER_NOTIFICATION_TEMPLATE_ID='已审核模板ID' \
CAREGIVER_NOTIFICATION_PAGE='pages/records/index' \
CLOUDBASE_ENABLE_NOTIFICATION_WORKER=1 \
CLOUDBASE_CONFIRM_WORKER_OPENAPI_PERMISSION=1 \
CLOUDBASE_CONFIRM_NOTIFICATION_SUBSCRIPTIONS=1 \
sh zykh_station_app/scripts/deploy_cloudbase_sync.sh
```

当前仓库没有外部小程序的订阅授权页面，也没有真实模板 ID；未完成这些现场条件
时不得设置上述启用开关。本轮不会发送真实微信通知或把本地 mock 结果表述为送达。

本仓库只包含 CloudBase 函数与可嵌入的小程序 helper，不包含外部 Windows
小程序工程的页面代码；部署前必须在实际小程序中接入页面、完成安全配对或受控建立 membership
数据并完成权限验收，不能把本地契约测试视为已上线。

## 配置与状态

参考 `backend/.env.example`。设备密钥只放在环境变量或：

```text
zykh_station_app/backend/data/cloud-device-secret.txt
```

不要提交密钥文件。

所有 Station 上报、快照、拉取和 ACK 动作都要求服务端已配置设备密钥；缺少
密钥时云函数会失败关闭，而不是把 `deviceId` 当成授权。安全事件读取和其他健康
读取使用小程序 OpenID membership，二者不能互相替代。

`device_pairing_codes`、`caregiver_notification_outbox` 与
`caregiver_notification_subscriptions` 只允许云函数服务端访问；不得给小程序开放
集合直读写规则。通知 worker 需要为 `state + createdAt` 的 PENDING 查询和
`state + claimedAt` 的 SENDING 收敛查询分别配置复合索引，并保留文档稳定 ID 的
唯一性。签发配对码还要求云函数环境配置按设备映射的 `DEVICE_SECRETS`，例如
`{"zykh-qsm-001":"<secret>"}`；真实密钥不得写入仓库或文档。

状态接口：

```text
GET /api/sync/status
POST /api/sync/run
```

`connected=true` 且 `last_sync_at` 持续更新表示双向轮询正常。断网时本地数据保留在 SQLite，恢复网络后自动补传。
