# zykh_station_app

`zykh_station_app` 是“智药康护”本机主应用。本机负责现代化界面、业务编排、本地数据、规则兜底和取药确认；QSM368ZP-WF 作为外设采集与执行控制网关，通过本机转发端口接入。

旧目录 `jetson_app/` 和 `zykh_app/` 只作为只读参考。新项目不依赖、不导入、不写入旧目录。

## 已完成范围

- 本机 FastAPI 后端骨架；
- SQLite 连接和初始化框架；
- QSM mock/real 双模式客户端，默认 mock；
- 首页、药品页、问询页、记录页；
- 药品页取药确认 dry-run；
- AI应急问询、风险提示、药品信息匹配、禁忌核验；
- 本地记录聚合和模拟同步队列；
- QSM real/mock 接入验证接口。
- 体征读取、扫码识别、dry-run 联调和外设能力展示入口。

## 安全边界

系统只提供应急问询、风险提示、药品信息匹配、禁忌核验、取药确认和安全出药执行能力。涉及中高风险、禁忌风险、重复服药风险或信息不足时，应转由专业人员处理。

## 运行方式

后端：

```bash
cd zykh_station_app
python -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
sh scripts/start_backend.sh
```

前端：

```bash
cd zykh_station_app/frontend
npm install
npm run dev
```

一键启动两个本机服务：

```bash
cd zykh_station_app
sh scripts/start_all.sh
```

访问：

```text
http://127.0.0.1:5173
```

## 配置

默认配置见 `backend/.env.example`：

```text
QSM_MODE=mock
QSM_BASE_URL=http://127.0.0.1:18080
QSM_TIMEOUT_SECONDS=2
DISPENSE_DRY_RUN=true
```

mock 模式不要求外设网关联通，必须能完整跑通首页、药品页、问询页和记录页。real 模式用于本机访问外设网关；如果 real 模式不可用，后端会返回结构化错误并让首页显示“暂不可用”，不影响主应用运行。

第六阶段采用最新硬件分工：摄像头由本机主应用直接检测和抓拍；体征、音频和药仓控制仍通过外设网关。`/api/qsm/camera/capture` 是现有业务流程的兼容入口，内部走本机摄像头服务，不依赖外设网关摄像头接口。

## QSM real 模式验证

外设网关可通过本机端口转发暴露到 `http://127.0.0.1:18080`：

```bash
cd zykh_station_app
sh scripts/adb_forward.sh
```

转发成功后启动后端：

```bash
QSM_MODE=real QSM_BASE_URL=http://127.0.0.1:18080 sh scripts/start_backend.sh
```

安全边界：`DISPENSE_DRY_RUN=true` 默认开启，第一阶段到第五阶段都不会真实出药。
第六阶段仍然只写入 dry-run 记录，不会真实出药。

## 第六阶段接口演示

mock 模式：

```bash
curl http://127.0.0.1:8000/api/qsm/vitals
curl -X POST http://127.0.0.1:8000/api/qsm/camera/capture
curl -X POST http://127.0.0.1:8000/api/qsm/dispense/dry-run \
  -H "Content-Type: application/json" \
  -d '{"slot":"B02","medicine_id":"lianhua-qingwen","quantity":1,"reason":"联调验证"}'
curl http://127.0.0.1:8000/api/qsm/capabilities
```

real 模式如果外设网关不可用，上述接口仍返回 HTTP 200 和结构化状态；前端只显示“暂不可用”等终端文案。

## 验证

```bash
python -m compileall zykh_station_app/backend/app
cd zykh_station_app/frontend && npm run build
```

## 阶段计划

1. 首页闭环和新架构基线；
2. 药品页 + 取药确认 dry-run；
3. 问询页 + AI rules 兜底；
4. 记录页 + 同步队列；
5. QSM real/mock 双模式接入验证；
6. QSM 外设功能联调入口；
7. 管理后台。
