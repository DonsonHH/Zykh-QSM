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

小程序反向操作通过 `commands` 集合完成。主机拉取命令并将其置为 `running`，执行后 ACK 为 `done` 或 `failed`。`cloud_command_history` 保存本地执行结果，同一命令 ID 即使重复下发也不会重复执行。

## 已同步数据

- 设备在线状态和同步代理版本；
- 23 个药柜仓位及药品信息，包括规格、追溯码、库存、低库存线和原始有效期精度；
- 服务对象；
- 今日计划；
- 体征记录；
- AI 问询记录；
- 家庭取药记录。

线上仍是旧版云函数时，终端自动使用 v1 兼容动作。药品写入 `medicines`，其余新增业务数据以结构化记录写入 `records`。部署 v2 云函数后会自动切换到 `service_users`、`today_plans`、`inquiries` 等独立集合。v2 还会锁定 schema 2 主代理：旧 `cloud_agent.pl` 不能再覆盖设备状态，也不能抢先拉取新命令。

## 部署 v2 云函数

先在微信云开发控制台创建集合：

```text
service_users
today_plans
inquiries
```

登录并部署：

```bash
tcb login
sh zykh_station_app/scripts/deploy_cloudbase_sync.sh
```

部署脚本会自动检查并创建 `service_users`、`today_plans`、`inquiries`，随后通过小体积 ZIP 直接更新现有 Event 云函数，保留原 `/api` HTTP 路由。它不会把函数类型改成 HTTP，也不依赖容易超时的 COS 上传；最终必须检测到 `schemaVersion=2` 才会成功退出。

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

返回中的 `schemaVersion` 应为 `2`，当前 `schemaRevision` 为 `2.4-medicine-safety-contract`。终端把 revision 纳入 snapshot hash；本次药品字段契约以及后续云函数清理或映射逻辑升级后会自动触发一次完整重同步。

## 小程序反向命令

可将 `cloudbase/miniprogram/remoteCommands.js` 放入小程序工具目录。它使用云函数 `CREATE_COMMAND`，避免页面直接拼装命令结构。

`cloudbase/miniprogram/stationSync.js` 提供 `loadStationSnapshot()` 和页面按需使用的 `subscribeStationSnapshot()`。订阅优先使用 CloudBase 数据库变更监听，5 秒周期刷新作为断线兜底；v2 下读取独立集合，v1 下自动从设备 `syncSummary` 和原有集合组合数据。2 秒设备心跳中的 `syncSummary.recentInquiries` 只携带摘要字段和 `messageCount`，不携带完整 `messages`。页面在 `onShow` 中建立订阅，并在 `onHide`/`onUnload` 中调用返回的停止函数。

`remoteCommands.js` 优先调用 v2 的 `CREATE_COMMAND`。只有云函数明确返回 `unknown action: CREATE_COMMAND` 时，才兼容为小程序直接写入旧版 `commands` 集合；网络超时、权限拒绝、命令类型或字段校验失败都会原样返回失败。CloudBase 自动附带的 `_openid` 仍由终端核验，确定性 `requestId` 也会防止重复创建同一次开柜请求。

`CREATE_COMMAND` 只接受微信小程序通过 `wx.cloud.callFunction` 发起的 Event 调用。公共 HTTP `/api` 即使携带相同 action 也会被拒绝，防止外部请求伪造远程开柜命令。

同步与命令兼容契约可在主机执行：

```bash
node zykh_station_app/cloudbase/miniprogram/test-sync-contract.cjs
```

支持：

```text
AUDIO_BEEP
READ_VITALS_ALL
AI_CHAT
UPSERT_MEDICINE
UPSERT_SERVICE_USER
UPSERT_TODAY_PLAN
OPEN_CABINET
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

远程开柜必须包含：

```json
{
  "slot": 8,
  "request_id": "open-唯一请求编号",
  "remote_confirmed": true,
  "actor_name": "家属",
  "reason": "家属端远程开柜"
}
```

终端还会核验命令来源的微信 OpenID、仓位范围和 `CLOUD_REMOTE_CABINET_ENABLED`。命令 ID 用于防止重复开柜；同一仓位 10 秒内的第二个远程开柜请求也会被拒绝。执行成功但 ACK 暂时断网时只补传结果，不会重新操作柜门。

## 配置与状态

参考 `backend/.env.example`。设备密钥只放在环境变量或：

```text
zykh_station_app/backend/data/cloud-device-secret.txt
```

不要提交密钥文件。

状态接口：

```text
GET /api/sync/status
POST /api/sync/run
```

`connected=true` 且 `last_sync_at` 持续更新表示双向轮询正常。断网时本地数据保留在 SQLite，恢复网络后自动补传。
