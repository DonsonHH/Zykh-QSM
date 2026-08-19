# 仓库文件与清理边界

本文说明 v1.9.0 发布时哪些文件进入 Git、哪些文件只保留在运行设备，以及哪些生成物可以安全清理。

## 进入版本库

| 类别 | 路径 | 原因 |
| --- | --- | --- |
| 主应用源码 | `backend/app/`、`frontend/src/` | 业务实现 |
| 自动化契约 | `backend/tests/`、`frontend/scripts/`、`qsm_gateway/tests/` | 回归验证 |
| 部署与运维 | `scripts/`、`qsm_gateway/` | 本机与板端部署 |
| 云同步源码 | `cloudbase/` | 云函数、小程序适配与契约 |
| 文档与示例配置 | `README.md`、`docs/`、`.env.example` | 部署、接口和边界说明 |
| 兼容参考 | `../zykh_app/` | 旧板端网关及维护工具；主应用不依赖其源码 |

## 只保留在运行设备

以下内容不进入 Git，但实际部署可能需要。清理前必须确认用途。

| 内容 | 默认位置 | 处理原则 |
| --- | --- | --- |
| Python 环境 | `backend/.venv/` | 保留；可由 `requirements.txt` 重建 |
| Node 依赖 | `frontend/node_modules/` | 保留；可由 `package-lock.json` 重建 |
| 生产构建 | `frontend/dist/` | 生产模式运行时保留；可由 `npm run build` 重建 |
| 私有配置与密钥 | `backend/.env.local`、`backend/data/` | 保留，禁止提交或写入文档 |
| 数据库与业务归档 | `data/` | 保留；数据库、身份影像和问询归档不是缓存 |
| Chromium 终端配置 | `data/chromium-kiosk/` | 终端运行时保留；只在明确重置浏览器状态时删除 |

## 可安全清理的生成物

- Python 的 `__pycache__/` 与 `*.pyc`；
- 已退出进程留下的 `*.pid`；
- 过期的本地调试日志；
- 未引用的临时截图和会话导出；
- 准备重新构建时的 `frontend/dist/`。

不要使用不带路径白名单的 `git clean -X`：它会同时删除 `.venv`、`node_modules`、本机配置和业务数据。

## v1.9.0 审计结果

| 对象 | 结果 |
| --- | --- |
| GitHub 分支 | 仅保留 `main`，没有待清理的远端功能分支 |
| GitHub Releases | 保留全部正式历史版本，作为审计与回退依据 |
| 历史调试流水账 | 从当前版本删除；有效连接结论已收敛到 `qsm-real-connection-audit.md` |
| 本机运行环境 | 保留 `.venv`、`node_modules`、`.env.local`、数据库和业务归档 |
| 本机生成物 | 清理临时会话、字节码缓存、旧日志、失效 PID 和未引用截图 |

## 发布验证

从仓库根目录执行：

```bash
bash zykh_station_app/scripts/verify_release.sh
```

自动化命令固定使用 `QSM_MODE=mock` 和 `DISPENSE_DRY_RUN=true`。真实硬件检查必须单独执行 [`demo-checklist.md`](demo-checklist.md) 中的步骤。
