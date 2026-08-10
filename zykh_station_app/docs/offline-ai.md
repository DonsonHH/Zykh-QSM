# 问询模型路由

终端的“联网”和“本地”是演示层模式，不是模型提供方选择器。两种模式都使用同一套云端大模型问询链路：逐轮信息抽取走 Chat Completions，最终分析和药品排序优先走 Responses，结构无效或端点不可用时回退到同一云端模型的 Chat Completions JSON 契约。

普通终端界面不会展示提供方、端点或回退细节。模式差异只有：

- 联网模式显示联网图标、运行微信小程序实时同步，并使用云端实时 TTS；
- 本地模式显示本地图标、暂停微信小程序实时同步，并使用 QSM 板端离线 TTS；
- 两种模式都保留物理 Wi-Fi/SIM 链路，问询都走云端模型；
- 云端模型不可用时，确定性规则只负责危险信号拦截、继续追问或安全失败提示，不伪装模型分析，也不生成药品排序。

## 生产配置

生产解析器会把历史 `AI_MODE=auto|local` 统一收敛为 `cloud`，把历史 `OFFLINE_INQUIRY_MODE=model` 收敛为 `rules`。这些旧变量仅为部署兼容保留，不再允许普通设置页切换到板端语言模型。

```text
AI_MODE=cloud
AI_API_BASE=https://api.deepseek.com/chat/completions
AI_RESPONSES_API_BASE=https://api.deepseek.com/responses
AI_MODEL=deepseek-v4-flash
AI_INQUIRY_REASONING_EFFORT=off
OFFLINE_INQUIRY_MODE=rules
```

密钥只从环境变量或本机私有文件读取，不写入 Git、Markdown 或前端资源。云端输出仍必须经过本地 schema 校验、危险信号规则、候选准入、禁忌/重复成分检查和开柜前实时复核。

## QSM 语言模型资产

仓库仍保留旧 QSM llama.cpp 部署与诊断脚本，供历史设备排障使用，但应用运行链路不会调用它。正式 `launch_kiosk.sh` 不提供重新启用该模型的环境开关，并会通过受限停止脚本幂等清退已知的旧模型进程，避免它与板端离线 TTS、ASR 和外设服务争用 2 GB 内存。

如需单独研究旧模型，必须脱离正式 kiosk 流程显式运行相关诊断脚本。该路径不属于当前产品问询契约，也不得被标记成联网或本地模式的正常结果来源。

## 验收

隔离测试应验证：

1. 联网和本地模式的问询请求都进入云端 provider；
2. 本地模式不会启动、探测或回退到 QSM llama.cpp；
3. 云端缺失密钥、失败或返回无效结构时，只返回规则连续性/安全失败结果，候选为空；
4. 模式切换不关闭实际 Wi-Fi/SIM；
5. 前端普通文案不暴露 provider、QSM 模型或内部路由名称。

测试必须使用 fake provider、临时数据库和 `QSM_MODE=mock`，不得访问真实密钥、QSM 或药柜。
