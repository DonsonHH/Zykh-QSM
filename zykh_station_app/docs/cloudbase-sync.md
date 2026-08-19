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

## v2.0.0 分类柜兼容边界

三分类柜改造只发生在本地界面、FastAPI 映射和 QSM 灯光执行层；本版本没有修改
`cloudbase/` 下的云函数、小程序 helper 或集合 schema，也不要求为该硬件变化重新
部署 CloudBase。云端继续看到 23 项药品逻辑库存身份：

- `hardware_slot=1..23` 仍是 `UPSERT_MEDICINE`、SQLite 行、快照和历史记录的稳定键；
- `cabinet_id=1..3` 只用于本机投影和实体分类柜指示灯，不上传替换 `hardware_slot`；
- 三个分类名称和 14/6/3 药品分组已作为 v2.0.0 本地实机布局确认，但不会写入 CloudBase，云端数据也不能用来重建该物理摆放；
- 云端仍无开柜或亮灯命令。历史 `OPEN_CABINET` 继续失败关闭，不会到达 QSM。

小程序允许的反向操作通过 `commands` 集合完成。主机拉取命令并将其置为 `running`，执行后 ACK 为 `done` 或 `failed`。`cloud_command_history` 保存本地执行结果，同一命令 ID 即使重复下发也不会重复执行。远程开柜不属于允许动作；历史 `OPEN_CABINET` 命令会被改写为失败且不会调用 QSM。

## 已同步数据

- 设备在线状态和同步代理版本；
- 23 项逻辑药品库存身份及药品信息，包括 `hardware_slot`、规格、追溯码、库存、低库存线和原始有效期精度；
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
caregiver_notification_subscriptions
device_memberships
device_pairing_codes
```

登录并部署：

```bash
tcb login
sh zykh_station_app/scripts/deploy_cloudbase_sync.sh
```

部署脚本会先只读核验既有 `api` 和同名通知 worker 的 Event 类型、Node.js
运行时、handler 及触发器集合；身份冲突时在创建集合或覆盖代码前失败关闭。
随后它检查并创建上述九个业务集合，用显式白名单小体积 ZIP 更新现有 `api`
Event 云函数并创建或更新独立 `caregiverNotificationWorker`。原 `/api` HTTP
路由不会被重建，测试文件不会进入 ZIP，也不依赖容易超时的 COS 上传。

worker 的唯一受管定时器会在更新代码前关闭；部署器只有在 API 返回
`schemaRevision=2.8-runtime-persona-consistency`，线上小程序运行时能力、人物
tombstone、配对签发与通知 worker 能力齐全，且 worker 自身无副作用运行探针
通过后，才可能执行最后的显式启用。
默认部署始终保持定时器关闭，部署或探针失败也不会留下 OPEN timer。

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
`2.8-runtime-persona-consistency`，并声明
`medicationSafetyEvents=v1`、`caregiverMembership=v1`、`devicePairing=v1`、
`devicePairingIssue=v1`、`caregiverNotificationOutbox=v1`、
`caregiverNotificationWorker=v1`、`inquiryDetail=v1`、`snapshotBatch=v2` 与
`serviceUserPersonaTombstones=v1`，以及小程序运行时使用的
`explicitInventoryState=v1`、`personaLifecycle=v1`、`vitalsAttribution=v1`。
终端把 revision 纳入 snapshot hash；后续云函数清理或映射逻辑升级后会自动
触发一次完整重同步。

人物迁移必须按“云先、Station 后”的顺序部署。2.8 云函数先兼容旧的
`<device>-user-<person>` 文档键；收到带代次的新行并成功写入 canonical 文档后，
只删除 `deviceId/personId` 精确匹配且代次为空或相同的旧键。无关、身份不匹配的
ownerless 文档不会被 `FINALIZE_SNAPSHOT` 或兼容迁移删除。随后部署 Station 并
触发一次完整同步，确认王奶奶、李爷爷为活动人物，旧张三、李四、王五为归档
tombstone，再发布依赖该能力的小程序版本。

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

同一 `CREATE_COMMAND.requestId` 在事务中绑定规范化请求摘要：相同内容安全重放，
不同内容返回 `IDEMPOTENCY_CONFLICT`，并发请求也不能互相覆盖。只读角色或缺少
`CREATE_COMMAND` 权限的 membership 不能下发命令。人物命令执行前还会从当前
唯一活动人物行重验 membership 绑定的代次，并由服务端把该代次写入命令；旧代次
授权不能向同 ID 的新人物发送问询或资料/计划更新。

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

`UPSERT_MEDICINE` 继续以 `hardware_slot`（兼容 `hardwareSlot` / `slot`）作为 1–23 的逻辑药品身份，不以条码去重，也不接受本地物理 `cabinet_id` 作为替代键。局部修改使用嵌套补丁：

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

终端只修改 `patch` 中明确出现的字段，库存和低库存线允许为 `0`。快照按逻辑 `slot` 升序提供药品；本地 1–3 分类柜映射不会写进这个同步表。命令字段到 SQLite 与快照字段的对应关系为：

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
才把核查与物理执行双轴合并写入同一条事件。为保持现有 CloudBase 契约，字段名和枚举不在 v2.0.0 中迁移；事件同时携带人物 profile revision、
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
