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

小程序允许的反向操作通过 `commands` 集合完成。主机拉取命令并将其置为 `running`，执行后 ACK 为 `done` 或 `failed`。`cloud_command_history` 保存本地执行结果，同一命令 ID 即使重复下发也不会重复执行。远程开柜不属于允许动作；历史 `OPEN_CABINET` 命令会被改写为失败且不会调用 QSM。

## 已同步数据

- 设备在线状态和同步代理版本；
- 23 个药柜仓位及药品信息，包括规格、追溯码、库存、低库存线和原始有效期精度；
- 服务对象；
- 今日计划；
- 体征记录；
- AI 问询记录；
- 家庭取药记录。
- 人物—药品安全核查及物理结果（独立 append-only 事件，不属于快照）。

线上仍是旧版云函数时，终端自动使用 v1 兼容动作。药品写入 `medicines`，其余新增业务数据以结构化记录写入 `records`。部署 v2 云函数后会自动切换到 `service_users`、`today_plans`、`inquiries` 等独立集合。v2 还会锁定 schema 2 主代理：旧 `cloud_agent.pl` 不能再覆盖设备状态，也不能抢先拉取新命令。

## 部署 v2 云函数

先在微信云开发控制台创建集合：

```text
service_users
today_plans
inquiries
medication_safety_events
caregiver_event_receipts
caregiver_notification_outbox
device_memberships
device_pairing_codes
```

登录并部署：

```bash
tcb login
sh zykh_station_app/scripts/deploy_cloudbase_sync.sh
```

部署脚本会自动检查并创建上述八个业务集合，随后通过小体积 ZIP 直接
更新现有 Event 云函数，保留原 `/api` HTTP 路由。它不会把函数类型改成
HTTP，也不依赖容易超时的 COS 上传；最终必须同时检测到
`schemaRevision=2.5-caregiver-safety-events`、`devicePairing=v1` 与
`caregiverNotificationOutbox=v1` 才会成功退出，不能把仍缺新 action 的旧 2.5
函数误判为部署完成。

也可以在微信开发者工具中，把 `zykh_station_app/cloudbase/cloudfunctions/api/` 复制为项目的 `cloudfunctions/api/`，然后右键选择“上传并部署：云端安装依赖”。

当前云开发环境：

```text
cloud1-d6gv6t2jf3f2c541c
```

部署后验证：

```bash
curl -sS -H 'Content-Type: application/json' \
  -d '{"action":"PING","data":{}}' \
  https://cloud1-d6gv6t2jf3f2c541c-1441069580.ap-shanghai.app.tcloudbase.com/api
```

返回中的 `schemaVersion` 应为 `2`，当前 `schemaRevision` 为
`2.5-caregiver-safety-events`，并声明 `medicationSafetyEvents=v1`、
`caregiverMembership=v1`、`devicePairing=v1`、
`caregiverNotificationOutbox=v1`、`inquiryDetail=v1` 与 `snapshotBatch=v2`。终端把
revision 纳入 snapshot hash；后续云函数清理或映射逻辑升级后会自动触发
一次完整重同步。

## 小程序反向命令

可将 `cloudbase/miniprogram/remoteCommands.js` 放入小程序工具目录。它使用云函数 `CREATE_COMMAND`，避免页面直接拼装命令结构。

`cloudbase/miniprogram/stationSync.js` 提供 `loadStationSnapshot()` 和页面按需使用的 `subscribeStationSnapshot()`。订阅以 5 秒周期调用经过 membership 校验的云函数；不再按可输入的 `deviceId` 直接 watch 健康集合，避免原始变更在授权投影前下发客户端。v2 下读取独立集合，v1 下自动从设备 `syncSummary` 和原有集合组合数据。2 秒设备心跳中的 `syncSummary.recentInquiries` 只携带摘要字段和 `messageCount`，不携带完整 `messages`，且 `GET_DEVICE` 会按当前家属人物范围裁剪摘要。页面在 `onShow` 中建立订阅，并在 `onHide`/`onUnload` 中调用返回的停止函数。

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

同一 `CREATE_COMMAND.requestId` 在事务中绑定规范化请求摘要：相同内容安全重放，
不同内容返回 `IDEMPOTENCY_CONFLICT`，并发请求也不能互相覆盖。只读角色或缺少
`CREATE_COMMAND` 权限的 membership 不能下发命令。

## 微信设备绑定

可将 `cloudbase/miniprogram/deviceMemberships.js` 嵌入实际小程序。它只通过
`wx.cloud.callFunction` 提供 `GET_MY_DEVICES`、
`REDEEM_DEVICE_PAIRING_CODE` 和能力检查，不读取或写入云数据库，也不会用本地
缓存的 `deviceId` 授权。两项绑定 action 只接受带当前微信 `OPENID` 的 Event
调用，公共 HTTP 调用失败关闭。

`device_pairing_codes` 是服务端专用集合。外部受控管理端创建配对码时必须使用
足够随机、至少 16 字符的一次性原文，集合中只保存 SHA-256：文档 ID 为
`pairing-<sha256(raw_code)>`，字段包含同一 `codeHash`、`deviceId`、`role`、
`permissions`、`service_user_scopes`、`status=UNUSED` 和带时区的 `expiresAt`；
不得保存原文。兑换请求只提交 `pairingCode`，云函数忽略调用者伪造的设备、角色
或权限，并在一个事务中重新校验哈希、未使用状态和过期时间，创建 ACTIVE
membership 后把码置为 `CONSUMED`。重复、过期、未知、已绑定或并发败方统一
返回 `PAIRING_CODE_INVALID`；`GET_MY_DEVICES` 只枚举当前 OPENID 的 ACTIVE
membership。

本仓没有 Station 管理端的配对码生成界面，也没有外部 Windows 小程序的扫码/
输入和设备切换页面。上线前还需在受控服务端生成高熵配对文档、将
`device_pairing_codes` 与 `device_memberships` 的数据库规则设为小程序端不可直读写，
并在实际小程序接入 helper 后完成双人并发、
过期和撤销验收；本次没有创建真实配对码或部署云函数。

同步与命令兼容契约可在主机执行：

```bash
node zykh_station_app/cloudbase/miniprogram/test-sync-contract.cjs
```

支持：

```text
AUDIO_BEEP
AUDIO_SPEAK
READ_VITALS_ALL
AI_CHAT
UPSERT_MEDICINE
UPSERT_SERVICE_USER
UPSERT_TODAY_PLAN
```

`UPSERT_MEDICINE` 以 `hardware_slot`（兼容 `hardwareSlot` / `slot`）作为药品身份，不以条码去重。局部修改使用嵌套补丁：

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

终端只修改 `patch` 中明确出现的字段，库存和低库存线允许为 `0`。快照按 `slot` 升序提供药品；命令字段到 SQLite 与快照字段的对应关系为：

| 命令字段 | SQLite | 小程序快照字段 |
|---|---|---|
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
`CHECK_FAILED` 在核查终态写入一条 outbox；`PASSED` 直到确认得到物理终态后，
才把核查与开柜双轴合并写入同一条事件。事件同时携带人物 profile revision、
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
事务幂等且保留首次 `readAt`。helper 不包含 REPORT、批准、解除、重试开柜
或任何数据库直写后备路径。

每次 `REPORT_MEDICATION_SAFETY_EVENT` 成功落库后，云函数会为当时仍是
ACTIVE、具备 `READ_SAFETY` 且人物范围匹配的每个 OPENID，在事务中同时补齐
UNREAD receipt 和一条 `caregiver_notification_outbox`。出站项以
`deviceId + eventId + recipientOpenId` 的 SHA-256 稳定键幂等，初始状态为
`PENDING`，只含事件 ID、设备 ID、收件人、membership ID 和模板键，不含药名、
人物名、病史、禁忌或问询内容；事件重放不会重复排队。REPORT 返回不等待微信
订阅消息发送，推送失败也不能删除事件或把 receipt 标为 READ。

本仓没有订阅消息模板、用户订阅授权流程或消费
`caregiver_notification_outbox` 的发送 worker，因此当前实现的可靠事实来源仍是
云端事件和小程序未读记录。上线前需单独配置最小文案模板与异步 worker；worker
认领 PENDING 项时必须再次验证 membership，发送结果只更新通知尝试状态，不能
修改安全事件或触发任何 Station 命令。本次没有伪造“已发送”状态，也没有发送
真实微信通知。

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

`device_pairing_codes` 与 `caregiver_notification_outbox` 只允许云函数服务端访问；
不得给小程序开放集合直读写规则。实际部署还应为通知 worker 的 `state + createdAt`
认领查询配置索引，并保留文档稳定 ID 的唯一性。

状态接口：

```text
GET /api/sync/status
POST /api/sync/run
```

`connected=true` 且 `last_sync_at` 持续更新表示双向轮询正常。断网时本地数据保留在 SQLite，恢复网络后自动补传。
