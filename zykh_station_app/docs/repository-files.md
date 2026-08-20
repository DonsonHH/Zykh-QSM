# 仓库文件与清理边界

本文说明 v2.0.0 发布时哪些文件进入 Git、哪些文件或快照只保留在本机，以及哪些生成物可以安全清理。

## 进入版本库

| 类别 | 路径 | 原因 |
| --- | --- | --- |
| 主应用源码 | `backend/app/`、`frontend/src/` | 业务实现 |
| 实体柜目录 | `backend/app/services/cabinet_v2_catalog.py` | 维护本地 9/8/6 实体摆放和 `cabinet_id=1..3`；不生成小程序 `storageBox` |
| 小程序药品投影 | `backend/app/services/medicine_cloud_projection.py` | 维护 `DAILY/CARE/PRESCRIPTION/COLD = 9/8/5/1` 与 S03/S13 canonical 身份适配；不控制实体柜 |
| 自动化契约 | `backend/tests/`、`frontend/scripts/`、`qsm_gateway/tests/` | 回归验证 |
| 部署与运维 | `scripts/`、`qsm_gateway/` | 本机与板端部署 |
| 三分类柜固件资料 | `qsm_gateway/firmware/cabinet_v2_l432kc/` | 已验证源码、链接脚本、接线/协议、测试和可复现构建说明；不含生成二进制 |
| 云同步源码 | `cloudbase/` | 云函数、小程序适配与契约 |
| 文档与示例配置 | `README.md`、`docs/`、`.env.example` | 部署、接口和边界说明 |
| 兼容参考 | `../zykh_app/` | 旧板端网关及维护工具；主应用不依赖其源码 |

## 只保留在本机或运行设备

以下内容不进入 Git，但实际部署可能需要。清理前必须确认用途。

| 内容 | 默认位置 | 处理原则 |
| --- | --- | --- |
| Python 环境 | `backend/.venv/` | 保留；可由 `requirements.txt` 重建 |
| Node 依赖 | `frontend/node_modules/` | 保留；可由 `package-lock.json` 重建 |
| 生产构建 | `frontend/dist/` | 生产模式运行时保留；可由 `npm run build` 重建 |
| 私有配置与密钥 | `backend/.env.local`、`backend/data/` | 保留，禁止提交或写入文档 |
| 数据库与业务归档 | `data/` | 保留；数据库、身份影像和问询归档不是缓存 |
| Chromium 终端配置 | `data/chromium-kiosk/` | 终端运行时保留；只在明确重置浏览器状态时删除 |
| v2 发布前快照 | 仓库同级的 `Zykh-QSM-snapshots/cabinet-v2-baseline-*` | 私有保留；包含完整 Git bundle、QSM 静态运行归档、ignored 硬件产物和整片 flash readback，不得推送到 GitHub |

## 可安全清理的生成物

- Python 的 `__pycache__/` 与 `*.pyc`；
- 已退出进程留下的 `*.pid`；
- 过期的本地调试日志；
- 未引用的临时截图和会话导出；
- 准备重新构建时的 `frontend/dist/`；
- `qsm_gateway/firmware/cabinet_v2_l432kc/build/` 中可由源码重建的 ELF、BIN、HEX 和 MAP。

不要使用不带路径白名单的 `git clean -X`：它会同时删除 `.venv`、`node_modules`、本机配置和业务数据。

## v2.0.0 基线与快照审计

| 对象 | 结果 |
| --- | --- |
| Git 基线 | 快照时本地 `main` 与 `origin/main` 均为 `c6b7bd98d9776455b199bc1133703aba6132d3f3`，ahead/behind 为 `0/0` |
| Git 历史快照 | 完整 all-refs bundle 已验证；SHA-256 `2555aaa22b644a61f924db6e76acb6cc41972b14fad6d0ef9223cf88e575d63a` |
| QSM 运行快照 | 静态归档排除滚动视频帧、日志和 PID；SHA-256 `28f3234d04889bbafc5d60a118e0d128566c78c4674d7c252b66b14386830e4e` |
| 固件快照 | 256 KiB readback 只保存在私有快照，SHA-256 `8f869a1cb39eda1a3562f7f5cc766627feafd6ac219e009d5eb262fc14b56766`；不进入 Git |
| 可重建固件 | 跟踪源码重建得到 1504 字节固件；选中板点亮第一排与最后三排，SHA-256 `91776e0fac42163f7151fb0e1c4df6cf2c2bb81b8e80c17581a77523776813db` |
| CloudBase | `cloudbase/` 不属于本次板端映射与同步适配范围，保持发布前基线代码；新的小程序药品投影由 Station 模块承担 |
| 本机运行环境 | 保留 `.venv`、`node_modules`、`.env.local`、数据库和业务归档 |
| 本机生成物 | 清理临时会话、字节码缓存、旧日志、失效 PID 和未引用截图 |

## 发布验证

从仓库根目录执行：

```bash
bash zykh_station_app/scripts/verify_release.sh
```

自动化命令固定使用 `QSM_MODE=mock` 和 `DISPENSE_DRY_RUN=true`。真实硬件检查必须单独执行 [`demo-checklist.md`](demo-checklist.md) 中的步骤。
