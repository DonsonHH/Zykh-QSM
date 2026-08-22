# Zykh-Miniprogram 与板端正确同步实施方案

> 状态：待实施，不代表已经部署
> 编写日期：2026-08-22（Asia/Shanghai）
> 板端事实基线：`Zykh-QSM@0edd9dcd73f7d49f81a1c74a1f312bc9b7630c44`
> 小程序审计基线：`Zykh-Miniprogram origin/main@9dd43c7401662348c04a8e1e4420a5b778c84604`
> 目标设备：`zykh-qsm-001`

## 1. 结论先行

小程序当前显示“等待药箱连接”的首要原因不是 STM32、柜灯或 Wi-Fi：

1. 板端 FastAPI 正常运行，网络实际走 Wi-Fi，实时同步开关已启用。
2. 板端 `/api/sync/status` 当前为 `connected=false`，最后成功同步时间是
   `2026-08-20 23:54:27`。
3. 线上 CloudBase `PING` 实际返回：

   ```json
   {
     "schemaVersion": 2,
     "schemaRevision": "2.7-runtime-consistency",
     "capabilities": {
       "snapshotBatch": "v2",
       "explicitInventoryState": "v1"
     }
   }
   ```

4. 当前板端要求 `schemaRevision=3.0-three-box-library`，且至少要求
   `snapshotBatch=v2`、`explicitInventoryState=v1`、
   `medicineStorageBoxes=v1`。线上云函数不满足，板端会在
   `REPORT_DEVICE` 之前停止，因此 `devices/{deviceId}.lastSeenAt` 不再刷新。
5. 小程序只要发现 `lastSeenAt` 超过 60 秒，就判定离线并显示“等待药箱连接”。

所以，**只改小程序页面文字或强制 `online=true` 不会恢复同步**。正确做法是：

```text
先修 Mini 仓库中的 CloudBase 3.0 实现和安全契约
  → 部署云函数并核对 PING
  → 让板端恢复 REPORT_DEVICE 与 23 药快照
  → 再发布修正过在线状态和药库投影的小程序
```

同时，Mini 最新远端还有两个产品级漂移：

- Mini 固定药库只有 22 种、9/8/5，并主动隐藏板端 S09；板端事实是
  23 种、9/8/6，S09 位于 3 号柜。
- Mini 把“正在加载、接口报错、文档不存在、心跳过期”都压成一个
  `online=false`，部分页面即使数据读取成功也会误报离线。

本方案以板端药品与分类数据为唯一事实源，不删除 S09，不允许小程序远程改药，
也不改 AI 应急问询代码。

## 2. 范围与非目标

### 2.1 本次必须完成

- 部署与板端兼容的 CloudBase 3.0 云函数。
- 恢复 `zykh-qsm-001` 的设备心跳和 23 药快照。
- 小程序按板端实际药品集合展示 23 种药，三个分类为 9/8/6。
- 修复小程序在线状态的数据丢失、错误吞噬和页面误报。
- 保留人物代次、配对、风险事件、体征归属和命令授权的失败关闭边界。
- 给出可回滚的云函数、数据和小程序发布顺序。

### 2.2 本次明确不做

- 不让小程序直连 Station 局域网或 STM32。
- 不让小程序发送 `OPEN_CABINET`、`DISPENSE` 或点灯命令。
- 不允许远端 `UPSERT_MEDICINE` 修改板端固定药库。
- 不上传本地 `cabinet_id`；云端只接收三类 `storageBox`。
- 不修改 AI 应急问询的模型、提示词、规则或匹配算法。
- 不用伪造 capability、伪造心跳或把错误显示成“在线”来绕过门禁。

## 3. 目标架构与事实边界

```text
Zykh-QSM Station（事实源）
  ├─ 23 种稳定药品身份
  ├─ 1/2/3 号实体柜与 9/8/6 分类
  ├─ 明确库存状态和现场记录
  └─ 每 2 秒主动 PING/REPORT_DEVICE/上传快照
                    │
                    ▼
CloudBase api（认证、存储、授权和队列）
  ├─ 校验 deviceId + 独立 deviceSecret
  ├─ 保存心跳与板端快照
  ├─ 按人物 ID + personaGeneration 隔离
  └─ 绝不把小程序输入当成药库事实
                    │
                    ▼
Zykh-Miniprogram（照护端只读投影）
  ├─ 从 CloudBase 读取板端药库
  ├─ 显示连接、同步新鲜度和最后成功时间
  ├─ 可发受控语音/体征命令
  └─ 不维护物理柜号、不远程开柜、不改固定药品
```

### 3.1 身份不可混用

- `medicineId`：跨端稳定药品身份，是云端文档身份。
- `hardware_slot` / `legacySlot`：旧版迁移兼容号，不是实体柜号。
- `cabinet_id`：板端本地物理柜号，只在 Station 使用，不上传 CloudBase。
- `storageBox`：小程序分组字段，只允许 `DAILY / CARE / PRESCRIPTION`。
- `deviceId`：本机和会员授权必须同时为 `zykh-qsm-001`，不能靠旧缓存猜测。
- `personaGeneration`：人物身份代次；相同人物 ID 的新旧代次不得互相可见。
- “药箱在线”：只表示 Station 最近 60 秒成功上报 CloudBase 心跳，不等于
  STM32、柜灯、摄像头或串口已经通过硬件健康检查；硬件健康必须使用独立字段和入口。

### 3.2 分类名称也以板端为准

| `storageBox` | 实体柜 | 小程序统一显示名 |
| --- | ---: | --- |
| `DAILY` | 1 | 日常用药 |
| `CARE` | 2 | 外用护理 |
| `PRESCRIPTION` | 3 | 慢病处方 |

Mini 现有“日常高频内服 / 外用消毒护理 / 慢病处方储备”应统一改成上表名称。
`storageBox` 是跨端分类码，实体柜号仍不进入 CloudBase 药品字段。

## 4. 板端权威药库

小程序不得再用自己的固定 22 药数组决定“哪些药存在”。当前板端权威映射如下：

| Station 本地编号 | 板端稳定 ID | 药品 | 实体柜 | 云端 `medicineId` | 云端兼容号 | `storageBox` |
| ---: | --- | --- | --- | --- | ---: | --- |
| 1 | `slot-01-fufang-ganmaoling` | 复方感冒灵颗粒 | 1 / 日常用药 | `slot-01-fufang-ganmaoling` | 1 | `DAILY` |
| 2 | `slot-02-centrum` | 多维元素片 | 3 / 慢病处方 | `slot-02-centrum` | 2 | `PRESCRIPTION` |
| 3 | `slot-03-diosmectite` | 蒙脱石散 | 1 / 日常用药 | `slot-13-montmorillonite` | 13 | `DAILY` |
| 4 | `slot-04-amoxicillin` | 阿莫西林胶囊 | 3 / 慢病处方 | `slot-04-amoxicillin` | 4 | `PRESCRIPTION` |
| 5 | `slot-05-nin-jiom-pei-pa-koa` | 蜜炼川贝枇杷膏 | 1 / 日常用药 | `slot-05-nin-jiom-pei-pa-koa` | 5 | `DAILY` |
| 6 | `slot-06-lactulose` | 乳果糖口服液 | 3 / 慢病处方 | `slot-06-lactulose` | 6 | `PRESCRIPTION` |
| 7 | `slot-07-yinhuang` | 银黄颗粒 | 1 / 日常用药 | `slot-07-yinhuang` | 7 | `DAILY` |
| 8 | `slot-08-huoxiang-zhengqi` | 藿香正气丸 | 1 / 日常用药 | `slot-08-huoxiang-zhengqi` | 8 | `DAILY` |
| 9 | `slot-09-bifid-triple` | 双歧杆菌三联活菌肠溶胶囊 | 3 / 慢病处方 | `slot-09-bifid-triple` | 9 | `PRESCRIPTION` |
| 10 | `slot-10-gauze` | 医用纱布敷料 | 2 / 外用护理 | `slot-10-gauze` | 10 | `CARE` |
| 11 | `slot-11-guilin-xiguashuang` | 桂林西瓜霜 | 1 / 日常用药 | `slot-11-guilin-xiguashuang` | 11 | `DAILY` |
| 12 | `slot-12-hydrotalcite` | 铝碳酸镁咀嚼片 | 1 / 日常用药 | `slot-12-hydrotalcite` | 12 | `DAILY` |
| 13 | `slot-13-ibuprofen` | 布洛芬缓释胶囊 | 1 / 日常用药 | `slot-03-ibuprofen` | 3 | `DAILY` |
| 14 | `slot-14-oseltamivir` | 磷酸奥司他韦胶囊 | 3 / 慢病处方 | `slot-14-oseltamivir` | 14 | `PRESCRIPTION` |
| 15 | `slot-15-mupirocin` | 莫匹罗星软膏 | 2 / 外用护理 | `slot-15-mupirocin` | 15 | `CARE` |
| 16 | `slot-16-ketoconazole` | 酮康唑乳膏 | 2 / 外用护理 | `slot-16-ketoconazole` | 16 | `CARE` |
| 17 | `slot-17-iodophor` | 碘伏消毒液 | 2 / 外用护理 | `slot-17-iodophor` | 17 | `CARE` |
| 18 | `slot-18-budesonide-nasal` | 布地奈德鼻喷雾剂 | 2 / 外用护理 | `slot-18-budesonide-nasal` | 18 | `CARE` |
| 19 | `slot-19-ketoprofen-gel` | 酮洛芬凝胶 | 2 / 外用护理 | `slot-19-ketoprofen-gel` | 19 | `CARE` |
| 20 | `slot-20-bandage` | 创口贴 | 2 / 外用护理 | `slot-20-bandage` | 20 | `CARE` |
| 21 | `slot-21-amlodipine` | 苯磺酸氨氯地平片 | 3 / 慢病处方 | `slot-21-amlodipine` | 21 | `PRESCRIPTION` |
| 22 | `slot-22-cotton-swab` | 医用棉签 | 2 / 外用护理 | `slot-22-cotton-swab` | 22 | `CARE` |
| 23 | `slot-23-desloratadine` | 枸地氯雷他定胶囊 | 1 / 日常用药 | `slot-23-desloratadine` | 23 | `DAILY` |

必须特别保护：

- S09 必须保留，属于 3 号柜和 `PRESCRIPTION`；不得隐藏、删除或改回 `COLD`。
- 板端 S03 蒙脱石散向云端投影为 `slot-13-montmorillonite`。
- 板端 S13 布洛芬缓释胶囊向云端投影为 `slot-03-ibuprofen`。
- 其余 21 种一一同值映射。
- 云端最终计数必须为 `DAILY=9`、`CARE=8`、`PRESCRIPTION=6`，总计 23。

## 5. CloudBase 3.0 修改方案

### 5.1 基线选择

从 Mini 的最新远端建立新分支，不要从本地已分叉的旧分支继续：

```bash
git fetch origin
git switch -c codex/board-authoritative-sync origin/main
git rev-parse HEAD
# 必须是 9dd43c7401662348c04a8e1e4420a5b778c84604
```

以 Mini `origin/main` 的 3.0 药品快照实现为功能基线，但**不能原样部署**，原因是它
尚未声明或完整实现板端全量同步要求的 `serviceUserPersonaTombstones=v1`，人物代次
和会员授权边界也比安全版 QSM 云函数弱。

也不能把 QSM 仓库里的 `cloudbase/**` 整目录覆盖过去；那个目录是 2.8 安全参考，
整包覆盖会丢掉 3.0 的稳定药品 ID、`storageBox` 和快照回执契约。

正确方法是：**以 Mini 3.0 为底，逐项移植 QSM 2.8 的人物代次安全 seam，并保留
Mini 3.0 的药品快照逻辑。**

### 5.2 PING 合同

PING 必须区分两个发布档位，不能只写一个“最终能力列表”。

#### Release A：心跳和药库限定同步

Release A 必须返回：

```json
{
  "ok": true,
  "schemaVersion": 2,
  "schemaRevision": "3.0-three-box-library",
  "capabilities": {
    "snapshotBatch": "v2",
    "snapshotFencing": "v1",
    "snapshotCanonicalDigest": "jcs-sha256-v1",
    "boardMedicineSnapshot": "v1",
    "explicitInventoryState": "v1",
    "medicineStorageBoxes": "v1",
    "caregiverMembership": "v1"
  }
}
```

Release A 明确**不得声明**：

```text
serviceUserPersonaTombstones
devicePairing
devicePairingIssue
remoteCommands
```

其它能力只有在其读取边界已经通过安全测试时才可保留，但不能让 Station 进入 full
sync 或开放新配对/命令。

Release A 的 membership 只用于选择授权设备及读取设备/药库。人物 scope 缺少严格
generation map 时，人物、计划、问询、体征、记录和风险接口必须返回“迁移中/无权限”，
不能使用 legacy fallback 暴露旧代次。

#### Release B：人物代次迁移后的最终合同

完成阶段 4 的人物、membership 和旧命令迁移后，最终 PING 才返回：

```json
{
  "ok": true,
  "schemaVersion": 2,
  "schemaRevision": "3.0-three-box-library",
  "capabilities": {
    "snapshotBatch": "v2",
    "snapshotFencing": "v1",
    "snapshotCanonicalDigest": "jcs-sha256-v1",
    "boardMedicineSnapshot": "v1",
    "explicitInventoryState": "v1",
    "medicineStorageBoxes": "v1",
    "medicationSafetyEvents": "v1",
    "caregiverMembership": "v1",
    "personaLifecycle": "v1",
    "serviceUserPersonaTombstones": "v1",
    "vitalsAttribution": "v1",
    "devicePairing": "v1",
    "devicePairingIssue": "v1"
  }
}
```

`remoteCommands=v1` 不随 Release B 自动开放；它属于单独的 Release C 闸门，必须在
旧队列清理和命令过期合同验收后才声明。能力只能在实现和测试都存在后声明。
`manualMedicationUse` 等尚未形成端到端闭环的能力不得仅为通过检查而虚报。

### 5.3 设备认证与心跳

修改 `cloudfunctions/api/index.js`：

- 生产环境仅使用 `DEVICE_SECRETS` 的逐设备密钥映射。
- `zykh-qsm-001` 必须存在对应密钥；不得把明文提交到 Git。
- `REPORT_DEVICE` 只接受正确 `deviceId + deviceSecret`。
- 云函数生成服务端时间，不信任客户端传来的 `online` 或时间。
- 除现有 `lastSeenAt` 外，新增数值型 `lastSeenAtEpochMs=Date.now()`，解决手机时区和
  无时区字符串解析歧义。
- `GET_DEVICE` 和 `GET_MY_DEVICES` 都返回 `lastSeenAt` 与
  `lastSeenAtEpochMs`，并由云函数按服务端时钟计算 `heartbeatAgeMs`；不得只返回
  一个永久为真的 `online` 布尔值。Mini 优先使用 `heartbeatAgeMs`，避免手机时钟
  偏差把新心跳误判为过期。

### 5.4 药品快照

保留 Mini 3.0 的 canonical identity 和 owner-scoped cleanup 语义，但不能保留其 batch
直接覆盖 live canonical 文档的写法。目标协议如下：

- `medicineSnapshotId = deviceId + canonical medicineId` 只作为版本内的逻辑行身份。
- batch 实际写入独立、不可变的版本化 staging collection，物理键至少包含
  `deviceId + kind + snapshotId/revision + canonicalRowId`；不得覆盖当前 manifest 所引用
  的文档。
- 先增加有 fencing 的快照会话：
  - Station 调用
    `BEGIN_SNAPSHOT {kind,rowCount,digest,canonicalDigestVersion,instanceId}`；
  - 云端返回一次性 `snapshotId` 和单调 `snapshotRevision`；
  - 每个 batch 和最终 finalize 都携带同一 `snapshotId/revision/digest`；
  - 云端只接受当前 active snapshot，拒绝旧实例、旧 revision 和迟到 finalize；
  - 同一 `deviceId` 只允许一个已登记的 active Station instance 写入。
  - BEGIN 返回有期限 lease。相同 instance+digest 可在 lease 内 resume；Station 把
    `snapshotId/revision/digest/lease` 持久化到 SQLite，重启后先续传而不是另建会话。
  - Station 可显式 `ABORT_SNAPSHOT`；lease 超时后，受认证的新 BEGIN 原子取得更高
    fencing revision 并接管，旧 revision 的 batch/finalize 永久拒绝。
  - staging 版本超时或被 abort 后先隔离，再按 TTL 延迟 GC；不能在接管瞬间删除审计证据。
- `UPSERT_SNAPSHOT_BATCH` 对 medicines 要求：
  - `medicineId` 非空；
  - camel/snake identity 不冲突；
  - `storageBox` 只允许 `DAILY / CARE / PRESCRIPTION`；
  - 同批次 ID 唯一，且云端在整个 snapshot session 内维护 canonical row ID 集合，跨
    batch 也必须全局唯一；每个 batch 的 ordinal/覆盖范围不得重叠；
  - 同一 `snapshotId + canonicalRowId` 的重试仅在 canonical bytes 完全相同时视为幂等；
    内容不同必须返回冲突，不得静默覆盖 staging 行；
  - 回执精确绑定 `{deviceId,kind,snapshotId,snapshotRevision,digest,count,ids}`。
- `FINALIZE_SNAPSHOT` 不立即删除旧 finalized 版本，而是把它标记为 superseded 并排入
  延迟 GC；ownerless 和其它 producer 也不在 finalize 内删除。
- finalize 只有在全部 batch、总行数和 digest 都已接收，且 session 级
  `uniqueCanonicalRowIds == rowCount`、manifest `uniqueIds == rowCount` 后，才在事务中原子切换
  authoritative manifest pointer；manifest 至少保存
  `{kind,snapshotId,revision,digest,ids,finalizedAt}`。切换前所有 reader 继续读取旧 staging
  版本，不能看到“新 20 条 + 旧 3 条”或同 ID 的新字段。
- serviceUsers 的 manifest pointer 与 current persona generation pointer 必须在同一事务
  切换，避免读到新人物行配旧 generation map。
- reader 必须在一次事务中读取 manifest pointer 和对应版本，或取得不可变 version token
  后只读该版本。superseded 版本至少保留
  `max(10 分钟, 2 × 最大读请求/重试窗口)` 后才 GC，保证切换前已在途的 reader 不会缺行。
- 新增 `GET_MEDICINE_SNAPSHOT`（或等价版本化 action），返回当前已完成 manifest envelope
  和其中的 Station-owned rows。ownerless、其它 producer 和尚未 finalize 的 staging 行
  可保留审计，但绝不能进入家庭端药库。
- 迁移期保留旧 `LIST_MEDICINES` 数组响应，但它的数据源也必须是同一 finalized manifest；
  这样存量 Mini 不会因响应形状改变而清空药库。旧接口只读、不得绕过 manifest。
- ownerless 历史行和其它生产者的行不得自动删除；若需要迁移，只按备份后的明确 ID 清单处理。
- `inquiries` 和 `vitals` 是有界历史窗口，只允许 append/update，服务端也应拒绝
  对这两个分区执行 finalize。
- `UPSERT_MEDICINE` 不作为新流程入口；CloudBase 和板端都失败关闭。
- 移除 `cleanupLegacyRecords()` 对 ownerless `SERVICE_USER/TODAY_PLAN/INQUIRY` 的自动
  删除；旧数据只能在备份后按明确 ID 清单做一次性迁移。

上述 fencing 需要 Station 的 `CloudSyncWorker` 同步携带/持久化 snapshot 会话字段，并把
`snapshotFencing=v1`、`snapshotCanonicalDigest=jcs-sha256-v1` 和
`boardMedicineSnapshot=v1` 都加入基础门禁。Station 本地
`cloud_snapshot_hash` 还必须包含 capability profile、manifest protocol version、
instance ID 和 digest；每轮先比对云端 finalized manifest，manifest 缺失或 digest 不一致
时强制重传，不能因旧本地 hash 相同而跳过。它们与 5.6 的 `remoteCommands` 独立闸门都是
必要板端协议配套改动，不能仅在 Mini 测试里伪造。

快照摘要固定为 `canonicalDigestVersion=jcs-sha256-v1`：先按 canonical row ID 排序 rows，
再按 RFC 8785 JSON Canonicalization Scheme 序列化并对 UTF-8 字节做 SHA-256；对象键、
字符串转义和数字采用 JCS 规则，数组内部顺序保留，布尔和 null 原样参与。摘要排除
`deviceSecret`、lease、服务器回执时间等传输字段，但包含 `deviceId/kind/rows`。
Python 与 JavaScript 必须共享同一组含中文、emoji、整数/小数、布尔、null 和乱序对象键的
golden vectors；BEGIN、batch receipt、manifest 和 PING 都携带/验证该版本。

### 5.5 人物代次和会员授权

将 QSM 安全实现中的下列能力合并进 Mini 3.0：

- 服务对象文档 ID 包含 `personId + personaGeneration`。
- 活动人物和 archived tombstone 都同步；旧代次不能被迟到的 active 行复活。
- `device_memberships` 保存 `service_user_generations` 映射。
- 签发配对码时，服务端重新确认每个作用域只有一个当前活动代次。
- 兑换配对码时再次核对代次；签发后人物代次已变化则拒绝兑换。
- 人物、计划、问询、体征、安全事件和命令读取都按
  `(service_user_id, persona_generation)` 过滤，不能只按姓名或 personId。
- 安全事件通知收件人在入队和发送前都复核代次。
- 创建人物相关命令时由云端写入当前代次，板端再次校验。

不能照搬 QSM 2.8 中“generation map 为空则兼容放行”的旧分支。Release B 的严格规则是：

- 每个 ACTIVE membership 的 `service_user_scopes` 必须非空，并与
  `service_user_generations` 的 key 集合完全相等。
- 每个 map value 必须等于该人物当前唯一活动代次；缺失、多余、空值或不匹配的
  membership 一律先 REVOKE，再由新配对码重建。
- VIEWER、CAREGIVER 和 OWNER 读取人物数据都必须有显式 scope+generation；无 scope 的
  设备管理员只能看设备级元数据，不能默认看所有历史人物。
- strict capability 开启后，`allowsPersona()` 遇到 empty map 必须返回 false，命令和
  通知也不能自动采用“当前代次”绕过会员绑定。
- 在 `devices/{deviceId}` 或独立 canonical pointer 文档保存当前人物 generation map 和
  revision；serviceUsers finalize 更新该指针。
- 配对签发、配对兑换和人物命令创建必须在事务内 condition-read 同一个 current pointer，
  再写 pairing/membership/command，防止事务前查询后人物换代的 TOCTOU。

涉及文件至少包括：

- `cloudfunctions/api/index.js`
- `cloudfunctions/api/memberships.js`
- `cloudfunctions/api/medicationSafetyEvents.js`
- 新增或移植 `cloudfunctions/api/serviceUserIdentity.js`

### 5.6 远端命令边界

Cloud 必须按 role、细粒度 permission、command type、人物 scope 和 generation 二次授权，
不能只检查通用 `CREATE_COMMAND`：

| 角色 | 命令 | 必需权限 | 人物规则 |
| --- | --- | --- | --- |
| VIEWER | 无 | 无 | 永久拒绝创建命令 |
| CAREGIVER | `AUDIO_BEEP` / `AUDIO_SPEAK` | `COMMAND_AUDIO` | 指定人物时必须命中 scope+generation；无人物仅允许显式设备测试 |
| CAREGIVER | `READ_VITALS_ALL` | `COMMAND_VITALS` | 人物测量必须绑定 scope+generation；独立测量显式 `STANDALONE` |
| OWNER | `AI_CHAT` | `COMMAND_AI` | 人物问询绑定 scope+generation |
| OWNER | `UPSERT_SERVICE_USER` | `MANAGE_PROFILE` | 只允许受控人物资料流程，不得覆盖旧代次 |
| OWNER | `UPSERT_TODAY_PLAN` | `MANAGE_PLAN` | 计划必须绑定当前人物代次 |
| 任意角色 | `OPEN_CABINET` / `DISPENSE` / 点灯 / `UPSERT_MEDICINE` | 不存在 | 永久拒绝 |

迁移时先移除旧 membership 的通用 `CREATE_COMMAND`，再按上表显式授予权限。角色本身
不能代替 permission，permission 也不能越过 role/type allowlist。
Mini 持久角色保持现有 `OWNER / CAREGIVER / VIEWER` 三种；部署运维管理员是后台身份，
不是新增的 membership `ADMIN` 角色，不能借迁移扩大角色集合。

- Release B 只开放全量数据同步，不开放命令；Station 只有看到额外
  `remoteCommands=v1` 才能执行 `_flush_unacked_commands/PULL_COMMANDS/ACK_COMMAND`。
- 新命令必须有服务端生成的 `createdAt/expiresAt`；PULL 在原子领取前先把过期命令标记
  `failed: COMMAND_EXPIRED`。旧的 pending/running 且无 expiry 的命令一律隔离，不重放。
- Station `_handle_command` 也必须独立校验服务端签发时间和 `expiresAt`；缺失、格式错误、
  位于未来的异常签发时间或已过期命令一律 failed。即使 Cloud 错误返回，板端也不得执行
  语音、蜂鸣、体征或其它副作用；用 fake-cloud 行为测试锁住这层防线。
- 相同 `requestId` 绑定规范化 payload 摘要；同 ID 不同内容返回
  `IDEMPOTENCY_CONFLICT`。
- 任何人物命令缺少或携带旧 `personaGeneration` 时失败关闭。

## 6. 小程序客户端修改方案

### 6.1 用显式连接状态替代 Boolean

在 `miniprogram/utils/api.js` 建立单一连接状态投影：

```js
{
  state: "loading" | "online" | "stale" | "unavailable" | "unpaired" | "incompatible",
  online: true | false | null,
  lastSeenAt: "...",
  lastSeenAtEpochMs: 0,
  heartbeatAgeMs: null,
  reason: "..."
}
```

规则：

- `online`：服务端心跳年龄小于 60 秒。
- `stale`：曾有合法心跳，但已超过 60 秒；此时才显示“等待药箱连接”。
- `loading`：首次请求尚未完成，显示“正在确认药箱状态”。
- `unavailable`：CloudBase、权限或数据库读取失败，显示“药箱状态暂不可用”。
- `unpaired`：当前微信账号无 ACTIVE membership，显示“请先配对药箱”。
- `incompatible`：PING revision/capability 不满足，显示“云端版本待升级”。

不得再用默认 `online=false` 同时代表以上五种不同状态。

连接状态和药品投影状态必须是两个独立轴。即使 heartbeat 新鲜，只要药品 manifest
capability/协议不兼容，仍应保持 `connection.state="incompatible"`，Header 显示“云端版本
待升级”；药库可另记 `medicineProjection.state="last-known" | "current" | "unavailable"`。
不得为了表达“正在显示上次药库”而把连接状态降成 `stale`，否则又会误显示“等待药箱连接”。

`getCapabilitiesStrict()` 返回的 `schemaVersion/schemaRevision/capabilities` 必须经过
`miniprogram/modules/deviceMemberships.js` 保留到 device session，再由
`miniprogram/app.js` 写入全局已解析 session。页面只能从这条真实链路得到
`incompatible`，不能仅在页面测试里手工 mock 一个不可达状态。

### 6.2 修复 API 错误语义

`cloudfunctions/api/index.js` 的 `GET_DEVICE`：

- 只有明确的 document-not-found 才返回结构化 `NOT_FOUND`。
- 数据库、权限或运行时异常必须返回 `ok:false`，不能 catch-all 后返回 `null`。

`miniprogram/utils/api.js`：

- `getDeviceStrict()` 遇到 null、缺 `deviceId` 或错误响应时必须 reject。
- 不再让兼容 `getDevice()` 把任意异常转成 `emptyDevice().online=false`。
- 状态驱动页面使用 strict/status-aware reader；已有成功快照时发生瞬时错误，应保留
  last-known 状态并标记 stale/unavailable，而不是覆盖成离线。

### 6.3 保留授权列表中的心跳字段

当前 `normalizeAuthorizedDevice()` 会丢掉云端已经返回的 `online` 和
`lastSeenAt`。修改 `miniprogram/utils/api.js` 与
`miniprogram/modules/deviceMemberships.js`，完整保留：

```text
deviceId
name
role
permissions
serviceUserScopes
serviceUserGenerations
lastSeenAt
lastSeenAtEpochMs
heartbeatAgeMs
connectionState
```

授权列表、当前选择设备和 `GET_DEVICE` 必须用同一套新鲜度函数，不能各自计算出
不同在线状态。

### 6.4 修复具体页面

| 文件 | 必须修改的行为 |
| --- | --- |
| `components/appHeader/index.js`、`index.wxml` | 接收显式状态；只有 stale 才显示“等待药箱连接” |
| `components/careScreen/index.wxml`、`utils/carePage.js` | 传递 connection state，不只传 Boolean |
| `miniprogram/app.js`、`modules/deviceMemberships.js` | 保留 PING schema/revision/compatibility 并贯通到页面 session |
| `pages/index/index.js` | 首页区分 stale、读取失败、未配对和协议不兼容 |
| `pages/settings/index.js` | 授权设备列表显示真实最后心跳和状态 |
| `pages/familyDetail/index.js` | 并行调用 `getDeviceStrict()`；不要读取不存在的 `snapshot.device` |
| `pages/medicationPlans/index.js`、`index.wxml` | 加载时显示“正在确认”，不得先闪“等待连接” |
| `pages/vitals/index.js` | 初始状态改为 loading，成功后再显示在线或 stale |
| `pages/cabinet/index.js`、`pages/library/index.js` | 改用 status-aware reader，读取失败不伪装离线 |
| `pages/addMedicine/index.js`、`pages/libraryList/index.js`、`pages/medicineList/index.js` | 同上；并逐步移除远端改固定药库入口 |
| `pages/medicationRisks/index.js`、`pages/records/index.js` | 保留最后成功状态，错误显示 unavailable |

### 6.5 轮询策略

- 保留页面可见时 20 秒轮询；这已足以覆盖板端 2 秒心跳和 60 秒离线阈值。
- 开发者工具当前把轮询抬到至少 60 秒，测试时必须了解这一差异。
- `onHide/onUnload` 继续释放 timer，避免开发者工具内存增长。
- 恢复网络后，下一轮轮询自动从 stale/unavailable 转为 online。
- 本轮不必直接监听数据库；不要为更快刷新绕过 Cloud Function 权限层。

## 7. 以板端数据重构 Mini 药库投影

### 7.1 删除“固定 22 药决定可见集合”的逻辑

当前 `miniprogram/data/fixedMedicineCatalog.js` 和
`miniprogram/utils/medicineLibrary.js` 会：

1. 固定生成 22 条药品；
2. 忽略不在数组里的云端行；
3. 因此必然隐藏 S09；
4. 在缺云端记录时仍可能显示一条本地静态药，造成“看起来已同步”的假象。

目标逻辑应改成：

```text
云端已 finalize 的 Station-owned manifest 决定“药品是否存在、库存、有效期、分类”
  + Mini 本地参考表仅补充展示用说明、标签和图标
  + manifest 内未识别但结构合法的板端 medicineId 仍显示，不得静默丢弃
  + manifest 外的 ownerless、其它 producer 或 staging 行一律不显示
  + 结构冲突的行进入“同步数据异常”，不得猜成 DAILY
```

### 7.2 具体改动

- 将 `FIXED_MEDICINES` 更新为 23 条，加入 S09，参考版本改为新的 23 药版本。
- 新版客户端调用 `GET_MEDICINE_SNAPSHOT`，只接受 `boardMedicineSnapshot=v1` 的完整
  manifest 响应；响应携带
  `snapshotId/revision/digest/snapshotComplete`，不再把任意 device 行混为药库。
- `LIST_MEDICINES` 作为只读数组兼容接口保留至少两个小程序发布周期；它同样只读取
  finalized manifest。兼容 action 对现有 Mini 的无参 `{}` 请求必须一次返回完整 23 行，
  不得沿用默认 `limit=20` 截断，也不得要求旧客户端新增分页参数。旧 Mini 会按其旧固定表
  隐藏 S09，但其余 22 项必须逐项来自云端 finalized rows，不能由本地静态表补出过期库存。
- 新版 Mini 可在 capability 缺失时识别旧数组并明确显示“客户端/云端待升级”，但不能把
  未带 manifest 证明的数组替换为新的权威药库；可继续展示
  `medicineProjection.state="last-known"`，同时保持连接状态为 `incompatible`，不能标记连接
  `stale`。
- `mergeFixedMedicineBaseline(rawMedicines)` 改为遍历 manifest 内去重后的 rows，而不是
  `FIXED_MEDICINES.map(...)`。
- 以 cloud row 的 `medicineId` 和 `storageBox` 为事实；本地参考只 enrich，不覆盖。
- 缺少 `medicineId`、storageBox 非法、camel/snake 冲突的行明确报错并隔离。
- 不再由 `legacySlot` 推断分类；slot 只用于兼容显示/迁移诊断。
- 展示计数必须来自本轮有效快照：9/8/6、总数 23。
- S03/S13 使用云端 canonical ID 显示正确名称，不按数字号交换药名。
- 删除或禁用小程序端新增/编辑固定药品和 `UPSERT_MEDICINE` 命令；药品维护提示应引导
  到 Station 现场操作。
- 删除 `miniprogram/utils/api.js` 中生产 `UPSERT_MEDICINE` 的 `saveMedicine()`，移除
  `pages/addMedicine/index.js` 的调用及 cabinet/medicineList 旧入口；即使这些页面当前
  未注册到 `app.json`，也不能保留可被未来误启用的写入 producer。
- 反转 `tests/command-submission.test.js` 的旧正向断言，改为静态/行为合同：客户端生产
  代码不存在 `UPSERT_MEDICINE` producer，Cloud 和 Station 对该命令都返回 failed。

建议修改：

- `miniprogram/data/fixedMedicineCatalog.js`
- `miniprogram/utils/medicineLibrary.js`
- `miniprogram/utils/api.js` 中的 `normalizeMedicine()`
- 药库、补药、有效期页面的计数和空状态
- `docs/FIXED_22_MEDICINES.md` 改为 23 药板端参考清单
- README、部署说明和三柜迁移文档中的 22、9/8/5 表述

## 8. 分阶段实施顺序

### 阶段 0：冻结和备份

1. 记录 QSM、Mini 和线上 CloudBase 的 commit/revision。
2. 将 QSM 当前尚未推送的提交安全推送或制作可恢复快照。
3. 备份 Station SQLite。
4. 导出 CloudBase 的 `devices`、`medicines`、`service_users`、`today_plans`、
   `inquiries`、`vitals`、`records`、`commands`、安全事件、membership、配对码和通知队列。
5. 同时导出数据库索引、安全规则、HTTP 触发器、通知 worker 的定时/触发配置、
   notification subscriptions/receipts、云函数并发数、超时和环境变量。
6. 保存当前 2.7 云函数版本；对备份做一次可读性和恢复演练，不能只确认“文件已生成”。
7. 记录现有 ACTIVE membership 对应的 `deviceId`、人物作用域和 generation map。
8. 密钥只通过 HTTPS 和最小权限环境/`0600` 文件注入，日志与错误统一脱敏。轮换时使用
   双密钥短窗口或停机原子切换，并保留可立即恢复的旧密钥；任何密钥均不进 Git/文档。

### 阶段 1：实现并离线验证 Mini/CloudBase

1. 从 Mini `origin/main@9dd43c7` 创建新分支。
2. 完成 CloudBase 3.0 安全合并、23 药投影和在线状态修复。
3. 在 QSM 的 `CloudSyncWorker` 增加 snapshot begin/fencing 字段、
   `snapshotFencing/boardMedicineSnapshot/snapshotCanonicalDigest` 基础门禁和
   `remoteCommands=v1` 独立闸门；药品事实和映射不改。
4. 先在本地 mock/测试环境完成跨仓全量测试，不连接真实板端。
5. 固定 CloudBase 和 QSM 部署包的 commit SHA；禁止从脏工作树直接部署。

### 阶段 2：云函数维护窗口

1. 暂停 Station CloudSync/FastAPI，避免云函数部署完成后 2 秒 worker 立即写入。
2. 在板端保持停止时，安装阶段 1 固定的新 QSM artifact，执行其 SQLite migration；核对
   运行代码 commit、schema migration、`BEGIN/ABORT_SNAPSHOT`、两项基础 capability 门禁、
   `remoteCommands` 闸门和板端命令 expiry 测试。不能继续运行当前不具备这些能力的
   `0edd9dc` artifact。
3. 新 QSM 此时面对旧 2.7 云端应继续失败关闭；不要为了试运行放宽门禁。
4. 部署新 `cloudfunctions/api`，保留所有既有环境变量。
5. 板端仍暂停时只读调用 PING，核对它与本文件 Release A 的 expected/forbidden
   capability 完全一致；此时 tombstone/pairing/remoteCommands 必须缺失。
6. 核对 `DEVICE_SECRETS` 含 `zykh-qsm-001`，只比较是否匹配，不打印密钥。
7. PING 不合格就保持板端停止，并成对回滚 QSM artifact/SQLite 与云函数，不能启动板端试错。

### 阶段 3：先恢复心跳和药库

最稳妥方式是按 Release A/B/C 分阶段发布：

1. 第一阶段云函数实现完整安全代码，但暂不声明
   `serviceUserPersonaTombstones=v1`；同时暂不声明 `devicePairing=v1` 和
   `devicePairingIssue=v1`，避免小程序展示一个当前无法闭环的新配对入口。
2. 启动板端后，它会进入“药库限定同步”：只执行
   `REPORT_DEVICE + medicines UPSERT/FINALIZE`，不会拉命令、同步人物或发送安全事件。
3. 验证 23 药、9/8/6、S09 和心跳后，再进行人物数据迁移。
4. 此阶段待处理安全事件仍保留在板端 outbox，不应要求清零。
5. 人物代次迁移完成前，小程序只开放设备与药库读取；人物相关页明确显示“数据迁移中”，
   不能回退到 legacy personId-only 读取。

此阶段只服务已经存在且核验无误的 ACTIVE membership。如果没有可用旧 membership，
不要回退到手填 deviceId 或绕过授权；先完成阶段 4，再声明配对能力并签发新配对码。

### 阶段 4：人物和全量同步

1. 再次暂停 Station worker，并冻结 `CREATE_COMMAND` 和通知 worker。
2. 将现有活动人物补齐稳定 `personaGeneration`，为归档人物保留 tombstone 和 current
   generation pointer/revision。
3. 审计每条 ACTIVE membership：scope 与 generation map 必须完全匹配；不确定、空 map、
   多余 scope 或旧代次全部 REVOKE 后重配。
4. 备份并清点所有 `pending/running/done_unacked` 命令。过期、无 `expiresAt`、缺代次或
   旧代次命令统一标记 failed/quarantined，绝不能在切换后重播语音、蜂鸣或体征读取。
5. 核对安全事件 outbox 的固定 wire payload/digest 和当前收件人；冻结期间不发送通知。
6. 在隔离设备/测试 deviceId 做 full-data canary，确认不拉命令、不发通知。
7. 发布 Release B PING，加入 `serviceUserPersonaTombstones=v1` 和配对能力，但仍不声明
   `remoteCommands=v1`；Station 只开放人物、计划、问询、体征、记录和风险事件同步。
8. 观察现有待处理 outbox 安全重放；同 event ID 必须复用第一次 wire payload/digest。
9. 恢复通知 worker 前复核 generation 收件人，并记录已发送通知不可回滚。
10. 最后单独发布 Release C `remoteCommands=v1`，用一条有 expiry 的 canary 命令验收后
    才开放真实远程语音/体征。

### 阶段 5：发布小程序

1. 用同一 CloudBase 环境真机预览。
2. 验证当前账号的 ACTIVE membership 和所选 `deviceId=zykh-qsm-001`。
3. 验证在线状态、23 药、三分类、页面错误状态和配对。
4. 上传小程序代码、提交审核，再正式发布。
5. 发布后继续观察至少一个 60 秒离线阈值和一次断网恢复周期。
6. 至少两个发布周期内保留旧 `LIST_MEDICINES` 数组兼容接口并监控版本使用；确认存量
   客户端升级后再单独计划下线，不能与本次上线同时移除。

## 9. 测试计划

### 9.1 Mini 单元与页面合同

新增或更新以下测试：

- `tests/device-membership-api.test.js`
  - GET_MY_DEVICES 的 `online/lastSeenAt/lastSeenAtEpochMs` 不丢失。
- `tests/device-memberships.test.js`
  - 二次归一化后心跳字段和授权设备仍一致；PING revision 可到达页面 session。
- `tests/device-session-bootstrap.test.js`、`tests/cloud-version-adapter.test.js`
  - 真实 PING 2.7/3.0 经 resolve/apply 后分别得到 incompatible/compatible，不靠页面 mock。
- `tests/strict-api-readers.test.js`
  - GET_DEVICE null/数据库错误必须 reject，不能返回假离线。
- `tests/home-care-priority.test.js`
  - loading/unavailable/unpaired/incompatible 不显示“等待连接”；只有 stale 显示。
- `tests/family-person-detail.test.js`
  - 不再伪造 `snapshot.device`，改用真实 `getDeviceStrict` mock。
- `tests/realtime-refresh.test.js`
  - 心跳恢复后下一轮转 online，旧设备迟到响应不能污染新设备。
- `tests/care-ui-design.test.js`、`tests/family-care-view.test.js`
  - 共享 Header 正确区分 loading/stale/unavailable，设置和家人页保留心跳字段。
- `tests/medication-plan-status.test.js`
  - 计划页首次加载不得闪“等待连接”，完成读取后再显示明确状态。
- `tests/vitals-summary-view.test.js`、记录页合同
  - 体征和记录页读取失败保留 last-known，并显示 unavailable 而非假离线。
- `tests/fixed-medicine-catalog.test.js`
  - 23 个唯一 identity、9/8/6、S09 存在、无 COLD。
- `tests/medicine-library.test.js`
  - raw cloud rows 决定可见集合；未知合法药不丢失；缺失药不凭静态表凭空补出。
- `tests/medicine-normalization.test.js`
  - S03/S13 canonical 映射和 identity/storageBox 冲突失败关闭。
- `tests/medicine-list.test.js`、`tests/strict-api-readers.test.js`
  - 缺 `boardMedicineSnapshot=v1`、缺 manifest 元数据或
    `snapshotComplete=false` 时，adapter 拒绝替换当前药库并保留 last-known；只有完整
    finalized manifest 才能进入 `mergeFixedMedicineBaseline()`。

### 9.2 CloudBase 安全合同

新增 Cloud Function 行为测试，至少覆盖：

- PING revision/capability 精确值。
- Release A/B/C 的 expected/forbidden capabilities 分别精确匹配，A 不得触发 full sync。
- 错 device secret 的所有 board action 均拒绝。
- REPORT_DEVICE 使用服务端时间并刷新 epoch。
- snapshot begin/revision/digest、23 药批次 ID、count、kind 回执与输入逐行一致；旧实例和
  迟到 finalize 被拒绝。
- 把重复 canonical medicine ID 分散在不同 batch 时，整个 session 失败关闭；重复 ordinal
  或覆盖范围被拒绝；同键同内容重试幂等、同键不同内容返回冲突；finalize 同时校验
  `uniqueCanonicalRowIds == uniqueManifestIds == rowCount`。
- 只写第一批 staging 后读取药库，旧 manifest 的行数和每个字段保持完全不变；finalize
  后才原子切换到新版本。
- BEGIN 后进程崩溃可由同 instance resume；lease 超时后新 revision 接管，旧实例随后
  batch/finalize 仍被拒绝；ABORT 和 TTL GC 不删除当前 manifest。
- 本地旧 `cloud_snapshot_hash` 相同但云端 manifest 缺失/digest 不同时，Station 强制重传；
  capability/profile 变化也必须改变本地 hash。
- FINALIZE 只原子切换 manifest 并把旧 Station-owned 版本标记为 superseded，不立即删除；
  grace period 内持有旧 version token 的 reader 仍能完整读取旧版本。延迟 GC 只清理已过
  保留期的 Station-owned superseded/staging 版本，绝不删除 ownerless/其它生产者。
- `GET_MEDICINE_SNAPSHOT` envelope 与旧 `LIST_MEDICINES` 数组都只读取当前 finalized
  manifest；ownerless、其它 producer 和 staging 合法药都不能成为第 24 项。
- 存量 Mini 以无参 `{}` 调用兼容 action 时，Cloud 必须返回完整 23-row finalized array，
  不得默认截成 20 行；逐项证明旧端显示的 22 个已知项都有对应 cloud row，只有 S09 被
  旧固定表过滤，不允许任何药品靠静态 baseline 补出库存或有效期。新版 reader 严格读取
  23 药 manifest，两个接口都不能因响应形状变化返回空药库。
- heartbeat online + 缺 `boardMedicineSnapshot` + 存在 last-known 药库时，Header 必须显示
  “云端版本待升级”，药品区可继续展示 last-known；不得显示“等待药箱连接”。
- inquiries/vitals finalize 被拒绝。
- 人物活动代次、归档代次、ID 复用、迟到 active 行。
- 空/错 generation map 的 membership 失败关闭；配对签发、兑换和命令事务中人物换代
  均失败关闭。
- 会员读取、风险通知和命令按 ID+代次过滤。
- role×permission×type 命令矩阵、命令 expiry、旧 pending/running 隔离，
  OPEN/DISPENSE/UPSERT_MEDICINE 拒绝。
- fake Cloud 返回缺失/非法/已过期 `expiresAt` 的命令时，Station 自身拒绝且没有任何
  语音、蜂鸣或体征副作用。
- 安全事件同 ID 同 digest 可重放、不同 digest 冲突。

### 9.3 自动化命令

在 Mini 仓库执行：

```bash
node --test tests/*.test.js
node tools/validate-miniprogram-ui.js
```

在 QSM 仓库执行既有板端合同和 release check，确认本次 Mini 方案没有要求放宽板端：

```bash
bash zykh_station_app/scripts/verify_release.sh
```

### 9.4 真机验收

1. `/api/sync/status.connected == true`，`last_error` 为空。
2. `devices/zykh-qsm-001.lastSeenAt` 持续刷新，正常间隔约 2 秒。
3. 小程序在一轮页面轮询内显示“药箱在线”。
4. 云端 medicines 恰好 23 个当前 owner 文档；三类为 9/8/6。
5. 在 finalize 前注入 staging/ownerless 行，小程序仍保留上一版完整药库且不显示这些行；
   finalize 成功后才原子切换 manifest。
6. S09 在慢病处方分类可见；无 COLD 分类。
7. S03 显示蒙脱石散，S13 显示布洛芬缓释胶囊，不能因兼容号互换药名。
8. 停止 Station 心跳超过 60 秒并越过一次轮询后，才显示“等待药箱连接”。
9. 模拟 GET_DEVICE 数据库错误时显示“状态暂不可用”，不能显示离线。
10. 恢复 Station 后自动转在线，无需重装小程序或手工改数据库。
11. 未配对账号只进入配对/授权页，不能看到其它设备数据。
12. 远端尝试 OPEN_CABINET、DISPENSE、UPSERT_MEDICINE 均失败，实体柜不动作。
13. full sync 后验证新旧人物代次隔离和安全事件回放，再开放远程语音/体征。

## 10. 回滚方案

### 10.1 PING 验证失败

- 保持板端暂停。
- 恢复已保存的 2.7 云函数版本和环境变量。
- 不改板端协议门禁；允许小程序继续显示离线，优先保证不误写。

### 10.2 药库同步失败

- 先停板端同步，再保存日志、PING 和 owner-scoped 数据差异。
- 回滚云函数。
- 按同一备份代次恢复 authoritative manifest pointer、snapshot session/lease、版本化
  staging 和 `zykh_station_app` owner 行；未完成/较新 staging 先隔离后清理，不能只恢复
  owner 行或做全集合清空。
- 若恢复了云端药品，还要成对恢复 Station SQLite，或在受控条件下失效
  `cloud_snapshot_hash`，否则本地哈希未变时不会自动重传。
- 绝不能以删除 S09、改回 22 药或放宽 receipt 校验作为修复。

### 10.3 人物/配对验收失败

- 先冻结命令创建、通知 worker 和 Station worker，再撤掉
  `remoteCommands/serviceUserPersonaTombstones` capability，使板端回到药库限定模式。
- 保留已同步的设备心跳和药品，不继续拉命令或发送人物数据。
- 成组恢复 membership/persona、plans/inquiries/vitals/records、commands、事件
  receipts/outbox、notification subscriptions 和 worker 配置；不能只回滚人物表。
- 已经播放的语音、执行的测量或发出的通知不可回滚，只能记录、告警并人工核查。
- 修复后先重复 full-data canary，再进入 Release B/C。

### 10.4 小程序发布失败

- 云函数和板端可保持已验证的 3.0 药库同步。
- 回滚小程序版本；旧 Mini 暂时可能只显示 22 药，但不得让旧客户端写药。
- 修复客户端后重新发布，不回滚板端 23 药事实。

## 11. 完成定义

只有以下条件全部满足，才可宣告“Mini 与板端正确同步”：

- [ ] 线上 PING 是 `2 / 3.0-three-box-library`，capability 与实现逐项一致。
- [ ] Release A/B/C 的 capability 闸门按顺序验收，没有提前开启人物或旧命令执行。
- [ ] 板端 `connected=true`，心跳持续刷新，不再停在 2026-08-20。
- [ ] Mini 的连接状态不是单一 Boolean，错误、加载、未配对和离线能被区分。
- [ ] 首页、家人详情、计划、药库、体征、记录页对同一设备显示一致状态。
- [ ] Mini 可见药品由板端快照决定，共 23 种、9/8/6，S09 可见。
- [ ] Mini 只读取 finalized Station manifest；ownerless/其它 producer 不会成为第 24 种。
- [ ] S03/S13 canonical 映射正确，未把旧兼容号当物理柜号。
- [ ] 小程序不能远程改药、开柜或点灯。
- [ ] 人物代次、配对、风险通知和命令权限测试全部通过。
- [ ] 迟到 snapshot finalize、旧 pending/running 命令和空 generation map 全部失败关闭。
- [ ] CloudBase、Station、Mini 三层均完成自动化与真机验收。
- [ ] 已演练一次云函数回滚和一次心跳中断/恢复。

## 12. 当前可立即执行的排障检查

在代码实施前，现场可用以下顺序确认现状；这些检查不会修复协议：

1. 板端读取 `GET /api/sync/status`。
2. 确认 `connected=false` 的错误仍是 revision/capability 不兼容。
3. 只读调用线上 PING，记录 revision，禁止打印 device secret。
4. 在 CloudBase 查看 `devices/zykh-qsm-001.lastSeenAt` 是否仍停在旧时间。
5. 在小程序“我的药箱”确认所选设备 ID 是 `zykh-qsm-001` 且 membership 为 ACTIVE。
6. 若未来 PING 和心跳恢复、但 Mini 仍显示等待，再依次检查：
   - `normalizeAuthorizedDevice` 是否保留心跳字段；
   - 当前页面是否调用 `getDeviceStrict`；
   - 是否处于开发者工具 60 秒轮询窗口；
   - 是否命中了不存在的 `snapshot.device` 旧逻辑。

这套顺序能把“真实心跳中断”和“小程序状态误报”明确分开，避免再次把所有问题都归为
网络、STM32 或一句模糊的“等待药箱连接”。
