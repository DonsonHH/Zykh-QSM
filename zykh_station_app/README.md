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
5. QSM real 接入 + 摄像头/体征/出药接口联调；
6. 管理后台。
