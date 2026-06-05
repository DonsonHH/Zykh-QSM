# 智药康护 QSM368ZP-WF 项目调试记录

## 项目目标

项目课题为“智药康护——基于 QSM368ZP-WF 的家庭智慧康护与智能用药”。目标是在 QSM368ZP-WF / RK3568 板子上本地运行一个前后端系统，接 HDMI 16:9 触摸屏，完成适老化终端 UI、药柜管理、用药提醒、摄像头识别、健康监测、AI 问诊和后续硬件控制。

## 板子环境

- 架构：`aarch64`
- 系统：`Buildroot 2018.02-rc3`
- 内核：`4.19`
- init：`init`
- 当前用户：`root`
- 可写目录：`/userdata`
- 无：`python3`、`pip3`、`node`
- 有：`perl`、`sqlite3`、`wget`、`gst-launch-1.0`、`v4l2-ctl`、`media-ctl`、`wpa_supplicant`、`wpa_passphrase`、`wpa_cli`、`udhcpc`
- 视频节点：`/dev/video-camera0`、`/dev/video0` 到 `/dev/video22`，实际验证 `/dev/video5` 可稳定出图
- I2C：`/dev/i2c-0`、`/dev/i2c-1`、`/dev/i2c-2`、`/dev/i2c-3`、`/dev/i2c-4`、`/dev/i2c-6`
- PWM：`/sys/class/pwm/pwmchip0` 到 `pwmchip3`
- UART：`/dev/ttyS1`、`ttyS3`、`ttyS4`、`ttyS5`、`ttyS7`、`ttyS8`

## 已实现内容

代码目录：`C:\Users\Donson\Documents\QSM368WF\zykh_app`

- `server.pl`：Perl 单文件 HTTP 后端，适配板子无 Python/Node 的情况
- `web/index.html`：适老化终端首页
- `web/admin.html`：管理/调试后台
- `web/camera.html`：摄像头大屏预览和拍照识别页
- `web/consult.html`：AI 问诊页
- `web/*.css`、`web/*.js`：前端样式和交互
- SQLite 数据库：`/userdata/zykh_app/data/zykh.db`

主要 API：

- `GET /api/status`：系统状态
- `GET/POST /api/medicines`：药品信息
- `GET/POST /api/plans`：用药计划
- `GET /api/records`：用药记录
- `POST /api/dispense`：出药控制，默认 1 号仓触发 `GPIO27` 500ms
- `POST /api/gpio`：GPIO 调试
- `POST /api/vitals/read`：健康数据读取，目前是演示数据
- `POST /api/recognize`：药品识别，目前是演示结果
- `POST /api/camera/capture`：摄像头拍照
- `GET /api/camera/frame`：单帧 JPG
- `GET /api/camera/stream`：浏览器 MJPEG 视频流，目标 30fps
- `POST /api/camera/stream/stop`：停止浏览器视频流
- `POST /api/ai/chat`：AI 问诊代理接口

## 摄像头方案

用户原始命令是把摄像头映射到 LVDS/Wayland：

```sh
echo 'output:LVDS-1:primary' > /tmp/.weston_drm.conf
export XDG_RUNTIME_DIR=/run
export WAYLAND_DISPLAY=wayland-0
gst-launch-1.0 -v v4l2src device=/dev/video-camera0 ! video/x-raw,format=NV12,width=640,height=480,framerate=30/1 ! videoconvert ! waylandsink sync=false
```

后续需求是不再映射到 LVDS/HDMI 原生预览，而是在浏览器里解决所有功能。因此改成浏览器 MJPEG：

```text
GET /api/camera/stream?width=640&height=480&fps=30
```

实现方式：

- 后端启动 GStreamer 后台进程，从 `/dev/video5` 以 NV12 640x480 30fps 连续抓图
- 用 `jpegenc` 编码 JPG
- 用 `multifilesink` 保留最新几帧
- Perl HTTP 接口以 `multipart/x-mixed-replace` 按 30fps 推送给浏览器
- 前端 `<img>` 直接播放 MJPEG
- 点击“拍照识别”前先调用 `/api/camera/stream/stop` 释放摄像头，再拍照

已验证：

- `/dev/video5` 手动 GStreamer 连续写 JPG 可生成图片
- `/api/camera/stream` 已输出 `--zykhframe` 边界和 JPEG 数据

复测更新：

- 2026-05-29 已复测 `POST /api/camera/capture`，返回 `ok:true`，拍照链路正常

## AI 问诊方案

DeepSeek 文档地址：`https://api-docs.deepseek.com/zh-cn/`

后端按 OpenAI 兼容格式调用 DeepSeek：

- 默认地址：`https://api.deepseek.com/chat/completions`
- 默认模型：`deepseek-v4-flash`
- API Key 只放后端环境变量，不写入前端
- 前端调用本地 `/api/ai/chat`
- 浏览器端使用 Web Speech API 做麦克风输入和语音播报

启动示例：

```sh
cd /userdata/zykh_app
AI_API_BASE='https://api.deepseek.com/chat/completions' \
AI_API_KEY='你的DeepSeek API Key' \
AI_MODEL='deepseek-v4-flash' \
perl server.pl --daemon
```

注意：

- 不要把真实 API Key 写入 Git、Markdown、HTML 或 JS
- Web Speech 的语音识别在 Chromium 里通常要求安全来源；`127.0.0.1` 通常可用，板子本地 kiosk 浏览器也应尽量用 localhost 访问
- 语音播报 `speechSynthesis` 通常是浏览器本地能力

## Wi-Fi 联网

用户提供的热点名称为 `964`。密码属于敏感信息，不写入本文档。

板子上可用联网命令：

```sh
wpa_passphrase '964' '<Wi-Fi密码>' > /userdata/wpa_964.conf
killall wpa_supplicant 2>/dev/null
mkdir -p /var/run/wpa_supplicant
ifconfig wlan0 up
wpa_supplicant -B -i wlan0 -c /userdata/wpa_964.conf -C /var/run/wpa_supplicant
sleep 8
wpa_cli -i wlan0 -p /var/run/wpa_supplicant status
udhcpc -i wlan0 -q -n
ifconfig wlan0
```

如果 `wlan0` 失败，改 `wlan1` 重试。当前调试中出现过：

- `wlan0`：`NO-CARRIER`
- `wlan1`：`wpa_state=SCANNING`
- DHCP 未拿到租约
- 扫描输出没有看到有效热点

建议排查：

- 热点开 2.4GHz
- 安全模式用 WPA2-PSK
- 不要隐藏 SSID
- 手机热点靠近板子
- 确认板载天线连接
- 用 `iw dev wlan0 scan | grep SSID` 确认能扫到 `964`

## 浏览器/前端展示方案

这块板子是 Buildroot，不是 Ubuntu/Debian，不能直接 `apt install chromium`。

可选路线：

1. 短期演示：电脑浏览器通过 `adb forward tcp:8080 tcp:8080` 访问 `http://127.0.0.1:8080`
2. 板子本地触屏：重编 Buildroot，加入浏览器壳
3. 推荐浏览器壳：`WPE WebKit + Cog` 或 Qt WebEngine kiosk
4. Chromium：理论可做，但编译重、依赖多、Wayland/GPU/内存适配成本高
5. 如果必须快速拥有 Chromium：换 Android 或 Ubuntu 镜像会更省时间

在只用板子的前提下，推荐先用 `WPE WebKit + Cog` 做 kiosk：

```sh
cog http://127.0.0.1:8080
```

如果后续 SDK/Buildroot menuconfig 可用，优先找这些包：

- `wpewebkit`
- `cog`
- `weston`
- `qt5webengine`
- `chromium` 或 `chromium-ozone-wayland`

## 常用部署命令

Windows PowerShell：

```powershell
cd C:\Users\Donson\Documents\QSM368WF
adb push .\zykh_app /userdata/
adb shell "perl -c /userdata/zykh_app/server.pl"
adb shell "pidof perl | xargs -r kill; pidof gst-launch-1.0 | xargs -r kill; cd /userdata/zykh_app && perl server.pl --daemon; sleep 1; pidof perl"
adb forward tcp:8080 tcp:8080
```

访问：

```text
http://127.0.0.1:8080/
http://127.0.0.1:8080/admin.html
http://127.0.0.1:8080/camera.html
http://127.0.0.1:8080/consult.html
```

## 后续优先级

1. 拿到 SDK 后决定浏览器壳：优先 WPE WebKit/Cog，其次 Qt WebEngine，最后 Chromium
2. 把药品识别从演示接口替换成真实 RKNN、本地模型或云端识别
3. 把健康监测从演示数据替换成真实 I2C/UART 传感器
4. 把 `GPIO27` 出药演示改成真实电机/PWM/驱动板控制
5. 后续上 HDMI 触屏后做一次 16:9 全屏 kiosk 适配和触摸交互测试

## 第二次开发记录

### 资料与代码接续

一开始用 `cmd type` 查看 Markdown 出现乱码，原因不是文件损坏，而是 cmd 代码页按非 UTF-8 读取。改用 PowerShell：

```powershell
Get-Content -Encoding UTF8
```

后续确认调试记录内容正常。第二次开发中的板端部署目录仍为：

```text
/userdata/zykh_app
```

当前会话已经从板端把新版 `server.pl`、`README.md` 和 `web/` 同步回本地：

```text
C:\Users\Donson\Documents\QSM368WF\zykh_app
```

### 后端服务状态

已验证过的部署流程：

```powershell
adb push .\zykh_app /userdata/
adb shell "perl -c /userdata/zykh_app/server.pl"
adb shell "cd /userdata/zykh_app && perl server.pl --daemon"
adb forward tcp:8080 tcp:8080
```

当 `http://127.0.0.1:8080/api/status` 能返回板子状态时，说明 Perl 后端、端口转发、静态页面和 API 链路都正常。

### 摄像头拍照修复

原问题：`POST /api/camera/capture` 返回 `ok:false`，但手动运行同一条 GStreamer 命令可以生成 JPG。

排查结论：

- `/dev/video5` 是当前稳定可用的摄像头节点
- `gst-launch-1.0 ... filesink location=/userdata/zykh_app/web/camera/latest.jpg` 可以生成图片
- API 调用后图片实际也生成了，但后端只看 `system()` 返回码，导致误判失败
- 进一步确认 `system()` 返回 `exit_code:-1`，原因是服务全局 `$SIG{CHLD} = 'IGNORE'` 影响子进程 `wait`

修复方式：

- 拍照成功判断改成：只要 `latest.jpg` 实际生成且非空，就返回成功
- 拍照日志写入 `/userdata/zykh_app/data/camera-capture.log`
- 执行 GStreamer 时局部恢复 `$SIG{CHLD}` 默认行为，让 `system()` 返回码正常

成功返回示例：

```json
{
  "ok": true,
  "exit_code": 0,
  "image_url": "/camera/latest.jpg",
  "detail": "摄像头拍照完成"
}
```

复测命令：

```powershell
curl.exe -s -X POST http://127.0.0.1:8080/api/camera/capture
```

### Wi-Fi 联网完成

一开始扫 `964` 时，PowerShell 把 `$i` 提前展开，导致命令没有真正按 `wlan0/wlan1` 扫描。后来显式指定接口后确认能扫描。之后实际改用热点 `Tan`。

使用板子已有脚本：

```sh
sh /userdata/medical_assistant/scripts/start_wifi.sh
```

已验证结果：

```text
ssid=Tan
wpa_state=COMPLETED
ip_address=192.168.43.59
```

网络信息：

- 默认网关：`192.168.43.1`
- DNS：`223.5.5.5`、`114.114.114.114`、`8.8.8.8`
- `ping 223.5.5.5` 成功
- `ping api.deepseek.com` 成功

结论：板子已经具备外网访问能力。`wget https://api.deepseek.com` 报错的原因是 Buildroot 里的 `wget` 不支持 HTTPS，不代表网络不通。

### DeepSeek AI 问诊打通

原后端用 `wget` 请求 DeepSeek，但板子环境限制如下：

- 有 `/usr/bin/openssl`
- 有 `HTTP::Tiny`
- 无 `IO::Socket::SSL`
- 无 `Net::SSLeay`
- `wget` 不支持 HTTPS

因此改为：

- `/api/ai/chat` 使用 `openssl s_client` 发送 HTTPS POST
- API Key 优先读取环境变量 `AI_API_KEY`
- 如果环境变量为空，则读取 `/userdata/zykh_app/data/ai-api-key.txt`
- 修复 DeepSeek 返回 `Transfer-Encoding: chunked` 的解析
- 修复中文 JSON 响应需要按 raw 字节读取的问题
- 请求临时文件用完后删除，避免 Authorization 长期留在磁盘

成功状态：

```json
{
  "ok": true,
  "source": "ai",
  "model": "deepseek-v4-flash"
}
```

Windows 下建议用 JSON 文件测试，避免 PowerShell 吃掉 JSON 双引号：

```powershell
$tmp = Join-Path $env:TEMP 'ai_req.json'
[IO.File]::WriteAllText($tmp, '{"message":"老人血压有点高，今天应该注意什么？"}', [Text.UTF8Encoding]::new($false))
curl.exe -s -H "Content-Type: application/json" --data-binary "@$tmp" http://127.0.0.1:8080/api/ai/chat
Remove-Item $tmp -Force
```

### 时间与北京时间统一

板子原时间曾是 2002 年，导致 HTTPS 证书报 `not yet valid`。处理方式是先用电脑 UTC 时间校准板子，再让服务默认显示北京时间。

`server.pl` 已加入：

```perl
$ENV{TZ} ||= 'CST-8';
POSIX::tzset();
```

验证结果示例：

```json
{
  "time": "2026-05-29 21:45:03"
}
```

每次板子重启后的建议启动顺序：

```powershell
adb shell "sh /userdata/medical_assistant/scripts/start_wifi.sh"

$utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')
adb shell "TZ=UTC date -s '$utc'; hwclock -w 2>/dev/null || true"

adb shell "cd /userdata/zykh_app && AI_MODEL='deepseek-v4-flash' perl server.pl --daemon"
adb forward tcp:8080 tcp:8080
```

### 当前进度

目前已经完成演示系统关键闭环：

- 后端服务运行
- 摄像头拍照
- Wi-Fi 联网
- DeepSeek AI 问诊
- 北京时间显示

还未完成或后续可继续推进：

- 浏览器壳还没做，当前主要靠电脑浏览器通过 `adb forward` 演示
- 药品识别仍是演示接口，尚未接 RKNN、本地模型或云端识别
- 健康监测仍是演示数据，尚未接真实 I2C/UART 传感器
- 出药控制仍是 GPIO 演示逻辑，尚未接真实电机/PWM/驱动板

## 2026-05-29 当前状态确认

本次查看后确认：

- 板端 `/userdata/zykh_app/server.pl` 是第二次开发后的新版，包含 `openssl s_client` 调 DeepSeek、chunked 解析、北京时间、拍照日志和 `local $SIG{CHLD}` 修复
- 已把板端新版同步回本地 `C:\Users\Donson\Documents\QSM368WF\zykh_app`
- 后端已重新启动，进程 PID 示例：`1355`
- `http://127.0.0.1:8080/api/status` 正常返回，时间为北京时间，系统为 `Buildroot 2018.02-rc3 / aarch64`
- `POST /api/camera/capture` 复测成功，返回 `ok:true`，使用 `/dev/video5`、`num-buffers=5`，输出 `/camera/latest.jpg`
- 初次 AI 测试失败原因是 Wi-Fi/DNS 未连接，错误为 `Temporary failure in name resolution`
- 执行 `sh /userdata/medical_assistant/scripts/start_wifi.sh` 后，Wi-Fi 连接 `Tan` 成功，IP 为 `192.168.43.59`
- `ping 223.5.5.5` 成功，`ping api.deepseek.com` 成功
- `/api/ai/chat` 复测成功，DeepSeek 返回中文健康建议，模型为 `deepseek-v4-flash`

当前演示访问地址：

```text
http://127.0.0.1:8080/
http://127.0.0.1:8080/camera.html
http://127.0.0.1:8080/consult.html
http://127.0.0.1:8080/admin.html
```

## 第三次开发记录

### AI 问诊 UI 优化

问诊页已按参考图改为更接近医疗终端的三栏布局：

- 顶部：品牌、日期时间、网络状态、紧急呼叫
- 左侧：老人头像/姓名/年龄、慢病、过敏史、最新体征、药柜库存、本次体征录入
- 中间：AI 助手聊天区，消息气泡、头像、底部语音/输入/发送
- 右侧：常见咨询两列快捷问题、安全提示
- 底部：医疗免责声明、设备编号、版本号

截图验证路径：

```text
C:\tmp\zykh-consult-final2.png
```

### Markdown 渲染

前端 `consult.js` 新增轻量 Markdown 渲染，支持：

- `**加粗**`
- `1. 有序列表`
- `- 无序列表`
- `### 小标题`
- `` `代码` ``

DeepSeek 流式返回的 delta 会持续拼接，页面中实时按 Markdown 渲染，避免 `**结论**` 原样显示。

### 原生浏览器方案

当前板子不能直接安装 Chromium。只用板子接 HDMI 触屏本地展示，建议顺序：

1. 首选 `WPE WebKit + Cog`，适合嵌入式 kiosk Web 应用
2. 备选 `Qt WebEngine`，基于 Chromium 但编译和运行成本更高
3. 独立 Chromium 不建议作为首选，Buildroot 依赖和适配成本高

SDK 内检查命令：

```sh
grep -R "BR2_PACKAGE_COG\|BR2_PACKAGE_WPEWEBKIT\|BR2_PACKAGE_QT5WEBENGINE" buildroot/package buildroot/.config 2>/dev/null
```

目标启动命令：

```sh
export XDG_RUNTIME_DIR=/run
export WAYLAND_DISPLAY=wayland-0
cog --platform=fdo http://127.0.0.1:8080/
```

如果走 DRM/KMS：

```sh
cog --platform=drm http://127.0.0.1:8080/
```

## 第四次开发记录

### 主页面 UI 重构

首页已按新的参考图重构为老人触屏终端：

- 顶部：品牌、语音欢迎条、网络状态、大时间
- 左侧：大时钟、开始取药
- 中部：下次服药提醒、测量体征、拍照识别药品
- 右侧：AI 问诊，替代原图里的紧急联系人
- 下方：药柜状态、系统状态、管理设置入口

截图验证路径：

```text
C:\tmp\zykh-home-redesign2.png
```

### 药品条码/溯源码识别与自动录入

新增本地药品目录表：

```text
medicine_catalog(code,name,dosage,manufacturer,batch_no,expire_date,trace_code,note,created_at)
```

新增接口：

```text
GET /api/medicine/lookup?code=6901234567890
POST /api/medicine/auto_add
```

首页“拍照识别药品”流程：

1. 调用 `/api/camera/capture` 拍照
2. 浏览器如果支持 `BarcodeDetector`，在本地识别 `qr_code`、`ean_13`、`ean_8`、`code_128`、`data_matrix`
3. 识别到条码/溯源码后调用 `/api/medicine/auto_add`
4. 后端查 `medicine_catalog`，得到药名、规格、厂家、批号、有效期
5. 自动写入 `medicines` 药柜表，并写入 `medicine_auto_add` 记录

当前内置 3 条演示目录：

- `6901234567890`：硝苯地平片，2026-12-31
- `6971234567891`：阿司匹林肠溶片，2026-10-31
- `6941234567892`：二甲双胍片，2027-03-31

已验证：

```text
GET /api/medicine/lookup?code=6901234567890
```

返回 `found:true`，可取到药名、规格、批号和有效期。

### 档案与长期记忆

新增长期记忆表：

```text
health_memories(type,title,content,happened_at,source,created_at)
```

新增接口：

```text
GET /api/memories
POST /api/memories
```

用途：

- 保存病例
- 保存随访记录
- 保存护理备注
- 保存异常体征事件
- 后续 AI 问诊时自动作为“记忆”写入 prompt

AI prompt 当前会自动包含：

- 老人基本档案
- 最近体征
- 最近病例/护理记忆
- 药柜库存和有效期

这样后续问诊不只是一次性对话，而是基于本地 SQLite 形成可追溯的家庭康护记忆。

## 第五次开发记录

### 23 仓药柜

根据手绘结构，药柜总数从 12 仓改为 23 仓：

- 大仓：8 个，约 `100 x 100 mm`
- 中仓：6 个，约 `100 x 65 mm`
- 小仓：9 个，约 `65 x 65 mm`

改动：

- 首页药柜摘要显示 `共23仓`
- 首页药柜模块增加“更多”按钮
- 新增完整药柜页面：`/cabinet.html`
- `/cabinet.html` 按实物草图展示：左侧 8 个大仓，右上 9 个小仓，右下 6 个中仓
- 后台管理仓位选择和新增药品最大仓位改为 23
- 自动录入药品时 `first_empty_slot()` 查找范围改为 1 到 23

截图：

```text
C:\tmp\zykh-home-23slots.png
C:\tmp\zykh-cabinet-23slots-final3.png
```

## 第六次开发记录：无浏览器 HDMI 原生 UI

时间：2026-06-01

### 第一步：确认无浏览器显示链路

由于当前 Buildroot 系统没有 `chromium`、`cog`、`qt5webengine`、`qmlscene`，短期不能直接在板子本地打开网页前端。

已确认板子具备另一条可演示链路：

- HDMI 已连接：`/sys/class/drm/card0-HDMI-A-1/status = connected`
- HDMI 可用模式包含：`1024x600`、`1920x1080`
- 触摸控制器已识别：`wch.cn USB2IIC_CTP_CONTROL`
- 已有 Weston：`/usr/bin/weston`
- 已有 Perl：`/usr/bin/perl`
- 已有 GStreamer：`/usr/bin/gst-launch-1.0`
- GStreamer 支持 SVG/PNG 解码：`gdkpixbufdec = 0`、`pngdec = 0`

结论：可以先不用浏览器，采用 `Perl 生成 SVG UI -> GStreamer 解码 -> Weston/HDMI 全屏显示` 的原生 UI 方案。Go 可以作为后续交叉编译后的替代实现，但当前板端和当前工作环境都没有 Go 编译/运行条件，因此不是最快演示路线。

### 第二步：跑通无浏览器 PNG HDMI UI

第一次尝试动态 SVG 管线时发现：

```text
multifilesrc -> gdkpixbufdec
```

在当前板端不能直接链接，日志报：

```text
could not link multifilesrc0 to gdkpixbufdec0
```

随后改为更稳的 PNG 静态界面链路：

```text
PNG 文件 -> multifilesrc loop=true -> pngdec -> videoconvert -> videoscale -> waylandsink fullscreen
```

已修正 `/userdata/zykh_app/scripts/start_png_hdmi_ui.sh`：

- 不再生成 300 张重复帧
- 只链接或复制一张 `native-screen-00000.png`
- 使用 `multifilesrc loop=true` 循环显示
- 不依赖当前系统缺失的 `imagefreeze`

已在板子上启动成功：

```text
Weston PID: 5193
GStreamer PID: 5213
HDMI status: connected
Wayland socket: /run/wayland-0
当前显示源: /userdata/zykh_app/native/screens/home.png
```

启动命令：

```sh
sh /userdata/zykh_app/scripts/start_png_hdmi_ui.sh home
```

切换药柜图：

```sh
sh /userdata/zykh_app/scripts/start_png_hdmi_ui.sh cabinet
```

停止：

```sh
sh /userdata/zykh_app/scripts/stop_native_hdmi_ui.sh
```

### 第三步：优化页面切换

第一次切换 `home` / `cabinet` 时，`start_hdmi_weston.sh` 每次都会重启 Weston，屏幕会闪烁。

已修正：

- 如果 Weston 已运行且 `/run/wayland-0` 存在，则复用当前 Weston
- 只有设置 `FORCE_WESTON_RESTART=1` 时才强制重启 Weston
- 切换页面时只重启 GStreamer 图层

验证结果：

```text
Weston PID: 5250
GStreamer PID: 5337
HDMI status: connected
当前页面: cabinet
```

当前干净进程状态：

```text
weston
weston-keyboard
weston-desktop-shell
gst-launch-1.0
```

### 第四步：改为 Go 原生 UI 方案

用户明确指出：最终不应靠裁切图片或网页截图，而应该用 Go 写新的本地 UI。

已停止继续把 PNG 方案作为最终方案。PNG/GStreamer 只保留为 HDMI 链路验证和临时兜底。

新增 Go 原生 UI：

```text
zykh_app/native/go-ui/go.mod
zykh_app/native/go-ui/main.go
zykh_app/native/go-ui/README.md
zykh_app/scripts/build_go_native_ui.ps1
zykh_app/scripts/start_go_hdmi_ui.sh
zykh_app/scripts/stop_go_hdmi_ui.sh
```

Go UI 设计：

- 不使用 Chromium、Cog、Qt WebEngine
- 不使用网页截图
- 直接写 Linux framebuffer：`/dev/fb0`
- 默认读取触摸事件：`/dev/input/event4`
- 使用本地字体：`/userdata/zykh_app/fonts/simhei.ttf`
- 通过本机 API 读取数据：`http://127.0.0.1:8080`
- 后端数据仍然来自当前 SQLite，不另起一套数据库

当前 Go UI 页面：

- 首页：时间、下次服药、开始取药、测量体征、拍照识别、AI 问诊入口、药柜状态
- 药柜页：23 仓布局，8 个大仓、9 个小仓、6 个中仓
- AI 页：第一版占位，后续接麦克风输入、语音播报和流式问诊内容

Windows 交叉编译命令：

```powershell
cd C:\Users\Donson\Documents\QSM368WF\zykh_app
.\scripts\build_go_native_ui.ps1
adb push .\zykh_app /userdata/
adb shell "chmod +x /userdata/zykh_app/bin/zykh-go-ui /userdata/zykh_app/scripts/*.sh"
```

板端启动：

```sh
sh /userdata/zykh_app/scripts/start_go_hdmi_ui.sh
```

板端停止：

```sh
sh /userdata/zykh_app/scripts/stop_go_hdmi_ui.sh
```

当前限制：

- 当前 Codex 工作环境没有 `go` / `gofmt`，所以本轮还不能在本机完成编译验证
- 板子上也没有 Go 运行/编译环境，因此需要在 Windows 或 SDK 主机上交叉编译出 `linux/arm64` 二进制后再推到 `/userdata/zykh_app/bin/zykh-go-ui`
- Go 程序使用 `golang.org/x/image` 渲染中文 TrueType 字体，编译时需要能执行 `go mod tidy`

已推送到板子：

```text
/userdata/zykh_app/native/go-ui/main.go
/userdata/zykh_app/native/go-ui/go.mod
/userdata/zykh_app/scripts/start_go_hdmi_ui.sh
/userdata/zykh_app/scripts/stop_go_hdmi_ui.sh
```

板端启动脚本已验证能正确检测缺失二进制：

```text
Go UI binary not found: /userdata/zykh_app/bin/zykh-go-ui
Please cross-compile native/go-ui for linux/arm64 first.
```

当前临时 PNG 显示进程已停止，只保留 Weston 进程，避免把临时图误认为最终 Go UI。

### 第五步：安装 Go、编译并启动 Go UI

时间：2026-06-01

用户要求直接在电脑和目标板子安装 Go，并执行编译/启动命令。

已下载官方 Go 工具链：

```text
go1.26.3.windows-amd64.zip
go1.26.3.linux-arm64.tar.gz
```

Windows 侧安装方式：

- 解压到工作区：`.tools/go-win/go`
- 不写入系统目录
- 版本确认：

```text
go version go1.26.3 windows/amd64
```

板子侧安装方式：

- 推送 `go1.26.3.linux-arm64.tar.gz` 到 `/userdata`
- BusyBox `tar` 不支持 `-z`，所以采用：

```sh
gzip -dc /userdata/go1.26.3.linux-arm64.tar.gz > /userdata/go1.26.3.linux-arm64.tar
tar -xf /userdata/go1.26.3.linux-arm64.tar -C /userdata
rm -f /userdata/go1.26.3.linux-arm64.tar
```

板子 Go 版本确认：

```text
go version go1.26.3 linux/arm64
```

Windows 编译时遇到权限问题：

```text
failed to initialize build cache at C:\Users\Donson\AppData\Local\go-build: Access is denied
```

已修正 `scripts/build_go_native_ui.ps1`：

- 自动优先使用 `.tools/go-win/go/bin/go.exe`
- `GOCACHE` 改到 `.tools/gocache`
- `GOPATH` 改到 `.tools/gopath`
- 编译前执行 `gofmt -w main.go`
- 脚本改为 ASCII 输出，避免 PowerShell 5.1 按错误编码解析中文字符串

编译结果：

```text
zykh_app/bin/zykh-go-ui
大小约 5.9 MB
目标：linux/arm64
```

第一次启动 Go UI 时遇到：

```text
zykh-go-ui: open framebuffer failed: invalid argument
```

原因：当前 `/dev/fb0` 的 ioctl 参数读取不完整，但 sysfs 有可用参数：

```text
/sys/class/graphics/fb0/bits_per_pixel = 32
/sys/class/graphics/fb0/stride = 4096
/sys/class/graphics/fb0/virtual_size = 1024,1280
```

已修正 `native/go-ui/main.go`：

- `FBIOGET_VSCREENINFO` / `FBIOGET_FSCREENINFO` 失败时不直接退出
- 回退读取 `/sys/class/graphics/fb0/virtual_size`
- 回退读取 `/sys/class/graphics/fb0/bits_per_pixel`
- 回退读取 `/sys/class/graphics/fb0/stride`
- 默认使用 XRGB8888 字段：R16/G8/B0/A24

重新编译并推送后，Go UI 启动成功：

```text
Go HDMI UI started
pid: 5576
fb: /dev/fb0
touch: /dev/input/event4
```

当前板子状态：

```text
zykh-go-ui PID: 5576
/userdata/go/bin/go version: go1.26.3 linux/arm64
/userdata/zykh_app/bin/zykh-go-ui: 5.9M
/userdata 剩余空间: 642M
```

当前 Go UI 已直接接管 framebuffer，不依赖 Chromium、Cog、Qt WebEngine、Weston 或 GStreamer。

重复编译脚本已验证通过：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\zykh_app\scripts\build_go_native_ui.ps1
```

输出：

```text
Go native UI built: ...\zykh_app\bin\zykh-go-ui
```

### 第六步：接续 Go HDMI UI 后续记录，改为 Go DRM/KMS 直显

时间：2026-06-02

用户提供后续调试记录：

```text
C:/Users/Donson/Downloads/Go HDMI UI 调试_055b419f2967.json
```

接续后确认的关键现象：

- Go UI 二进制能够启动，触摸环境变量也正确。
- 直接写 `/dev/fb0` 时，画面有时出现，有时又掉回原 Weston 桌面。
- 停止 Weston 后，Go 进程仍在，但 HDMI 会变成 `no signal`。
- 说明 `/dev/fb0` 不是稳定的 HDMI 独占显示路径，Weston/DRM 仍在控制真实 HDMI 输出。
- 用户明确要求不要把当前 UI 画成 PNG 文件中转，也不要走截图式方案。

因此本轮撤销了临时 PNG 输出思路，改为 Go 直接操作 DRM/KMS：

- Go 程序打开 `/dev/dri/card0`。
- 通过 `DRM_IOCTL_MODE_GETRESOURCES` 枚举 CRTC、connector、encoder。
- 选择 connected 的 HDMI connector。
- 创建 DRM dumb buffer。
- `ADDFB` 后用 `SETCRTC` 直接设置 HDMI 输出。
- 每秒由 Go 直接把 UI 的 RGBA 像素写入 DRM 显存。
- 触摸仍读取 `/dev/input/event4`。
- `/dev/fb0` 仅保留为备用调试路径。

板端 DRM 状态确认：

```text
/dev/dri/card0
/dev/dri/card1
/dev/dri/renderD128
/dev/dri/renderD129
```

`modetest -M rockchip` 确认 HDMI 可用：

```text
connector 156 HDMI-A-1 connected
preferred mode 1280x720
other modes include 1920x1080, 1024x768, 720x576, 720x480
```

第一次 Go DRM 枚举失败：

```text
no connected DRM connector with usable mode
connector 154 error=bad address
connector 156 error=bad address
connector 167 error=bad address
```

原因：第二次读取 connector 时，内核要求同时提供 properties 和 property values 数组地址。只提供 modes/encoders 会导致 `EFAULT bad address`。

已修复 `native/go-ui/main.go`：

- 新增 `renderSink` 抽象。
- 新增 DRM/KMS 显示后端。
- 新增 DRM 结构体和 ioctl 请求。
- connector 二次读取时补齐 `props`、`prop_values`。
- `ZYKH_RENDER_TARGET=drm` 时走 DRM 直显。
- `ZYKH_RENDER_TARGET=fb` 时保留旧 framebuffer 备用路径。

已修复 `scripts/start_go_hdmi_ui.sh`：

- 启动前停止 Weston、GStreamer、旧 Go UI。
- 设置：

```sh
ZYKH_RENDER_TARGET=drm
ZYKH_DRM_CARD=/dev/dri/card0
ZYKH_TOUCH_EVENT=/dev/input/event4
ZYKH_API_BASE=http://127.0.0.1:8080
```

重新编译、推送、启动后成功：

```text
Go HDMI UI started
pid: 1458
render: drm
drm: /dev/dri/card0
touch: /dev/input/event4
```

当前板端进程确认：

```text
zykh-go-ui: 1458
weston: none
gst-launch-1.0: none
HDMI: connected
```

当前推荐启动方式：

```powershell
cd C:\Users\Donson\.codex\worktrees\930c\QSM368WF
powershell -NoProfile -ExecutionPolicy Bypass -File .\zykh_app\scripts\build_go_native_ui.ps1
adb push .\zykh_app /userdata/
adb shell "chmod +x /userdata/zykh_app/bin/zykh-go-ui /userdata/zykh_app/scripts/*.sh"
adb shell "sh /userdata/zykh_app/scripts/start_go_hdmi_ui.sh"
```

停止：

```powershell
adb shell "sh /userdata/zykh_app/scripts/stop_go_hdmi_ui.sh"
```

后续注意：

- 不再把 Go UI 画成 PNG 文件，也不再依赖浏览器显示主 UI。
- 当前 Go UI 已直接走 DRM/KMS，理论上不会再被 Weston 桌面覆盖。
- 如果 HDMI 屏幕比例要求 16:9，当前 DRM 会优先选择 HDMI 首选模式，板端实测为 1280x720。
- 下一步需要用户观察 HDMI 屏幕是否持续显示 Go UI，不再掉回桌面或 no signal。

### 第七步：按用户要求改为 Weston 桌面上的 Go 原生全屏应用

时间：2026-06-02

用户反馈：

```text
DRM/KMS 直显后屏幕又变成 no signal。
希望直接做一个程序放在桌面上全屏，不霸占 HDMI 端口空间。
```

因此本轮不再把 DRM/KMS 直显作为主路线，改为：

```text
Weston 继续负责 HDMI/DRM 输出
Go 程序作为 Wayland 客户端运行
Go 程序创建全屏窗口
Go 程序自己绘制 UI
触摸仍读取 /dev/input/event4
```

这样它是“桌面上的原生全屏应用”，而不是独占 HDMI、不是浏览器、不是 PNG/截图/GStreamer 中转。

已修改 `native/go-ui/main.go`：

- 新增 `ZYKH_RENDER_TARGET=wayland`。
- Go 内部直接连接 Wayland socket：

```text
/run/wayland-0
```

- 通过 Wayland registry 绑定：

```text
wl_compositor
wl_shm
xdg_wm_base
```

- 创建 xdg toplevel 窗口并调用 fullscreen。
- 用 Wayland shared memory buffer 承载 Go 绘制出的像素。
- 每秒刷新 UI，同时保留触摸事件处理。
- 进一步绑定 `wl_output`，选择当前模式为 `1024x600` 的输出作为 fullscreen 目标，以匹配 Weston 日志中的 HDMI-A-1 当前模式。

已修改 `scripts/start_go_hdmi_ui.sh`：

- 不再停止 Weston。
- 改为调用项目脚本启动稳定 Weston 底座：

```sh
sh /userdata/zykh_app/scripts/start_hdmi_weston.sh
```

- 设置：

```sh
XDG_RUNTIME_DIR=/run
WAYLAND_DISPLAY=wayland-0
ZYKH_RENDER_TARGET=wayland
ZYKH_UI_WIDTH=1024
ZYKH_UI_HEIGHT=600
ZYKH_TOUCH_EVENT=/dev/input/event4
```

重新编译、推送、启动后成功：

```text
Weston started: 1717
HDMI status: connected
Wayland: /run/wayland-0
Go HDMI UI started
pid: 1734
render: wayland
wayland: /run/wayland-0
touch: /dev/input/event4
```

5 秒后复查：

```text
zykh-go-ui: 1734
weston: 1717
HDMI: connected
go-ui.log: no error
```

随后补充了 fullscreen 输出选择逻辑，重新编译推送并重启成功：

```text
Weston already running: 1717
HDMI status: connected
Wayland: /run/wayland-0
Go HDMI UI started
pid: 1778
render: wayland
wayland: /run/wayland-0
touch: /dev/input/event4
```

再次 5 秒后复查：

```text
zykh-go-ui: 1778
weston: 1717
HDMI: connected
go-ui.log: no error
```

当前推荐启动方式保持不变：

```powershell
adb shell "sh /userdata/zykh_app/scripts/start_go_hdmi_ui.sh"
```

当前结论：

- 主显示路线改为 `Weston + Go Wayland fullscreen`。
- DRM/KMS 直显保留在代码中作为备用调试路径，但不再作为默认启动方式。
- `/dev/fb0` 也只作为备用路径，不再作为 HDMI 主 UI 路线。
- 这个方案符合“原生程序放在桌面上全屏”的要求。

### 第八步：打通 HDMI 当前画面抓屏识别

时间：2026-06-02

用户希望能识别当前 HDMI 上显示的界面，方便后续调试。

第一次直接运行 `weston-screenshooter` 失败：

```text
screenshooter failed: permission denied. Debug protocol must be enabled
```

已修改 `scripts/start_hdmi_weston.sh`：

```sh
weston --backend=drm-backend.so --tty=1 --idle-time=0 --debug --current-mode
```

作用：

- `--debug`：启用 Weston screenshooter 调试协议。
- `--current-mode`：优先保持当前 HDMI 模式，避免重启 Weston 时切换分辨率。

新增抓屏脚本：

```text
zykh_app/scripts/capture_hdmi_screenshot.sh
```

板端执行：

```sh
sh /userdata/zykh_app/scripts/capture_hdmi_screenshot.sh
```

输出固定文件：

```text
/userdata/zykh_app/runtime/hdmi-current.png
```

电脑端拉回：

```powershell
adb pull /userdata/zykh_app/runtime/hdmi-current.png .\hdmi-current.png
```

本次实际抓屏结果：

- Weston 截图可用。
- `weston-info` 确认 HDMI 输出为：

```text
make: DWE
model: HDMI
x: 0
y: 0
width: 1024
height: 600
current mode: 1024x600@59.821
```

- 抓到的 HDMI 区域能看到“智药康护”界面，但右侧/底部有 Weston 桌面或测试窗口残留。
- 查到曾有 `glmark2-es2-way` 覆盖画面，已把启动脚本加入清理：

```sh
killall glmark2-es2-way
killall glmark2-es2-drm
killall weston-simple-egl
killall weston-simple-shm
```

后续调试 UI 显示时，优先使用抓屏脚本，不再只靠肉眼描述。

### 第九步：修复 HDMI 实际屏幕只露出 UI 右侧的问题

时间：2026-06-02

用户提供实际 HDMI 屏幕照片，现象为：

```text
HDMI 上大部分是 Weston 蓝色桌面背景；
底部还有 Weston 图标栏；
右侧只露出一条“智药康护”界面。
```

原因判断：

- 不是 Go UI 没启动，也不是 HDMI no signal。
- Weston 同时启用了多个输出：`HDMI-A-1`、`LVDS-1`、`DSI-1`。
- Go Wayland 全屏窗口被放到了多屏桌面布局中的非 HDMI 区域或边缘，所以 HDMI 上只看到 UI 的一部分。

修复方式：

修改 `scripts/start_hdmi_weston.sh`，启动 Weston 前生成专用配置：

```ini
[core]
idle-time=0

[shell]
locking=false
panel-position=none

[output]
name=HDMI-A-1
mode=current

[output]
name=LVDS-1
mode=off

[output]
name=DSI-1
mode=off
```

并用该配置启动 Weston：

```sh
weston --backend=drm-backend.so --tty=1 --idle-time=0 --debug --current-mode --config=/userdata/zykh_app/runtime/weston-hdmi.ini
```

同时修改 `scripts/start_go_hdmi_ui.sh`：

```sh
FORCE_WESTON_RESTART=1 sh /userdata/zykh_app/scripts/start_hdmi_weston.sh
```

确保每次启动 Go UI 前，Weston 都按 HDMI-only 配置重启。

验证结果：

```text
weston PID: 1599
zykh-go-ui PID: 1615
weston-info:
  output name: HDMI-A-1
  logical_x: 0
  logical_y: 0
  logical_width: 1024
  logical_height: 600
```

重新抓屏后，HDMI 当前画面已经干净显示 Go 原生首页：

```text
智药康护首页完整铺满 1024x600；
无右侧残留；
无 Weston 底部图标栏；
无 glmark/Tux 测试窗口覆盖。
```

当前主显示链路最终定为：

```text
Weston HDMI-only 桌面
  -> Go Wayland 全屏原生应用
  -> /dev/input/event4 触摸输入
```

### 第十步：优化 Go 原生 UI，并补齐拍照识别和 AI 问诊页面

时间：2026-06-02

基于 HDMI 抓屏结果继续优化板端 UI。

本轮首页问题：

- 板端字体不支持部分符号，原先的图标显示成方块。
- 右侧卡片的说明文字有截断。
- 绿色“开始取药”按钮右侧箭头白底白字，不明显。

已修改 `native/go-ui/main.go`：

- 将不稳定符号图标替换成中文单字图标：

```text
药 / 测 / 拍 / AI / 音
```

- 将右侧卡片说明缩短，避免 1024x600 下溢出。
- 将箭头统一改为 ASCII `>`，避免字体缺字。
- 首页最终抓屏确认：

```text
zykh-ui-home-final.png
```

新增拍照识别页面：

- 页面名：`camera`
- 入口：首页“拍照识别”
- 包含：

```text
摄像头画面区域
拍照识别按钮
重新识别按钮
自动录入药柜按钮
识别结果面板
药品名称
识别信息
建议仓位
有效期
识别说明
```

- 交互：

```text
点击“拍照识别”或“重新识别”
  -> POST /api/camera/capture
  -> POST /api/recognize
  -> 更新识别结果
```

- 当前摄像头预览区域先显示 Go 原生占位画面，后续可继续接入实时摄像头帧。
- 拍照识别页抓屏确认：

```text
zykh-ui-camera.png
```

新增 AI 问诊页面：

- 页面名：`ai`
- 入口：首页“AI 问诊”
- 包含：

```text
患者档案侧栏
慢性疾病
最新体征
药柜可用药
AI 助手对话区
语音按钮
常见咨询按钮
安全提示
```

- 常见咨询按钮：

```text
头晕血压高怎么办
今天适合吃哪些药
药品副作用咨询
体检指标怎么看
睡眠不好怎么办
```

- 交互：

```text
点击常见咨询
  -> POST /api/ai/chat
  -> 显示 AI 回复
```

- 语音按钮当前作为入口提示，后续继续接麦克风输入和语音播报。
- AI 问诊页抓屏确认：

```text
zykh-ui-ai.png
```

新增调试环境变量：

```sh
ZYKH_START_PAGE=home
ZYKH_START_PAGE=camera
ZYKH_START_PAGE=ai
```

用于直接启动到指定页面，方便抓屏调试：

```powershell
adb shell "ZYKH_START_PAGE=camera sh /userdata/zykh_app/scripts/start_go_hdmi_ui.sh"
adb shell "ZYKH_START_PAGE=ai sh /userdata/zykh_app/scripts/start_go_hdmi_ui.sh"
```

最终已恢复首页启动：

```text
Go HDMI UI started
page: home
render: wayland
HDMI: connected
```

### 第十一步：AI 问诊优化、北京时间、麦克风录音和溯源码扫码

时间：2026-06-02

用户反馈：

```text
AI 问诊页面做得不够好，需要接近之前的设计；
板子有麦克风模块；
时间要改成现实世界时间；
摄像头实际存在，需要做扫码识别药品溯源码，获得药品信息和保质期。
```

#### Wi-Fi 与现实时间

已按用户指定命令连接 Wi-Fi：

```sh
/userdata/medical_assistant/scripts/start_wifi.sh
```

实际结果：

```text
wpa_state=COMPLETED
ssid=Tan
ip_address=192.168.43.59
DNS: 223.5.5.5 / 114.114.114.114 / 8.8.8.8
```

随后用电脑当前时间校准板端时间：

```powershell
$utc=(Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')
adb shell "TZ=UTC date -s '$utc'; hwclock -w 2>/dev/null || true; date"
```

已修改启动脚本：

- `scripts/start_go_hdmi_ui.sh`：加入 `TZ=CST-8`
- `scripts/start_zykh_server.sh`：加入 `TZ=CST-8`

验证 `/api/status`：

```text
"time":"2026-06-02 22:02:56"
```

说明界面和 API 已按北京时间显示。

#### 麦克风模块

板端确认存在音频设备：

```text
/dev/snd/pcmC0D0c
arecord
aplay
card 0: rockchip,rk809-codec
```

录音参数测试：

```text
hw:0,0 -c 1 失败：Channels count non available
hw:0,0 -c 2 成功
plughw:0,0 -c 1 成功
plughw:0,0 -c 2 成功
```

新增后端接口：

```text
POST /api/audio/record
```

默认录音命令：

```sh
arecord -q -D plughw:0,0 -f S16_LE -r 16000 -c 1 -d 3 /userdata/zykh_app/data/audio/last-question.wav
```

验证成功：

```json
{
  "ok": true,
  "device": "plughw:0,0",
  "file": "/userdata/zykh_app/data/audio/last-question.wav",
  "detail": "麦克风录音完成；后续可接 RKNN Whisper 做语音转文字。"
}
```

本地 examples 中存在 RKNN Whisper demo：

```text
examples/rknn/rknn_whisper_demo
```

但当前目录缺少实际 `.rknn` 模型文件，仅有链接说明，所以本轮只打通录音链路，未假装已完成语音识别。

#### AI 问诊 UI 优化

已优化 `native/go-ui/main.go` 的 AI 页面：

- 标题改为“AI 健康咨询终端”
- 三栏布局：

```text
左侧：患者档案、慢病、最新体征、药柜可用药
中间：AI 助手信息、聊天气泡、麦克风按钮
右侧：常见咨询、安全提示
```

- 麦克风按钮从占位改为调用：

```text
POST /api/audio/record
```

- 常见咨询仍调用：

```text
POST /api/ai/chat
```

抓屏确认：

```text
zykh-ai-v3.png
```

#### 摄像头与溯源码扫码

板端确认摄像头存在：

```text
/dev/video5
/dev/video-camera0
v4l2-ctl
```

板端当前没有：

```text
zbarimg
zbarcam
```

因此新增后端接口：

```text
POST /api/medicine/scan
```

流程：

```text
调用 /api/camera/capture 拍照
如果安装了 zbarimg，则用 zbarimg --raw 解码条形码/二维码/DataMatrix
如果没有 zbarimg，则使用演示溯源码 TRACE6901234567890 跑通流程
调用 /api/medicine/lookup 查询本地 medicine_catalog
Go UI 再调用 /api/medicine/auto_add 自动录入药柜
```

本轮接口验证：

```json
{
  "ok": true,
  "scanner": "demo-no-zbar",
  "code": "TRACE6901234567890",
  "lookup": {
    "found": true,
    "medicine": {
      "name": "硝苯地平片",
      "dosage": "10mg*30片",
      "expire_date": "2026-12-31"
    }
  }
}
```

自动录入验证：

```json
{
  "ok": true,
  "found": true,
  "slot": 4,
  "medicine": {
    "name": "硝苯地平片",
    "expire_date": "2026-12-31"
  }
}
```

说明：

- 当前已跑通“拍照 -> 溯源码 -> 查本地目录 -> 自动录入药柜”的演示闭环。
- 真实图像解码需要后续加入 `zbarimg`、RKNN 码识别模型，或企业/药监追溯接口。
- Go 原生扫码页已改成“扫码识别药品”，显示溯源码、有效期、识别信息和自动录入结果。

#### 本轮最终状态

```text
Perl server syntax OK
ZYKH server started
Go HDMI UI started
page: home
render: wayland
Wi-Fi: connected
API time: 2026-06-02 北京时间
audio record: ok
medicine scan demo: ok
auto add: ok
```

### 第十二步：Go 原生 UI 实时视频、AI 对话动效与页面动画

#### 本轮目标

用户提出三个继续优化点：

```text
1. 摄像头画面需要实时展示，同时做到图像解码
2. AI 问诊界面要更像对话界面，并且更灵动
3. 页面切换需要动画
```

本轮继续坚持原则：

```text
不把 UI 画成 PNG 文件
不依赖浏览器
继续使用 Go 原生程序直接绘制 HDMI 触摸屏界面
```

#### 已完成：摄像头实时预览

Go 原生 UI 已接入后端 MJPEG 视频流：

```text
GET /api/camera/stream?width=640&height=480&fps=15&quality=75
```

实现方式：

```text
Go UI 进入扫码页后自动启动后台 HTTP 读流
解析 multipart/x-mixed-replace
逐帧 jpeg.Decode
将 JPEG 帧转换为 image.RGBA
按比例铺入扫码页摄像头预览区域
页面刷新频率由 1Hz 提高到 10Hz
扫码时临时停止实时流，释放摄像头后调用 /api/medicine/scan
扫码结束后如果仍停留在扫码页，则自动恢复实时预览
```

已在 HDMI 抓屏验证：

```text
hdmi-camera.png
扫码页出现真实摄像头画面
界面显示：实时预览 8 fps
```

当前性能说明：

```text
当前后端 MJPEG 流基于 GStreamer multifilesink 写临时 JPG，再由 Perl 轮询最新文件推流。
这条链路已经可用，但写盘和轮询会限制帧率。
如果后续要稳定接近 25/30fps，建议改成 GStreamer 管道直出或 appsink/管道读取，减少磁盘中转。
```

#### 图像解码现状

本轮验证后端扫码接口仍可用：

```sh
wget -qO- --post-data='' http://127.0.0.1:8080/api/medicine/scan
```

返回结果：

```json
{
  "ok": true,
  "scanner": "demo-no-zbar",
  "code": "TRACE6901234567890",
  "lookup": {
    "ok": true,
    "found": true,
    "medicine": {
      "name": "硝苯地平片",
      "dosage": "10mg*30片",
      "expire_date": "2026-12-31"
    }
  },
  "image_url": "/camera/latest.jpg"
}
```

限制：

```text
板端当前没有 zbarimg / zbarcam，也没有 GStreamer zbar 插件。
所以真实条形码/二维码/溯源码图像解码还没有完成。
当前 /api/medicine/scan 会使用演示溯源码跑通流程。
```

后续可选实现路线：

```text
1. 给 Buildroot 镜像加入 zbar，后端直接调用 zbarimg 解码 latest.jpg
2. 编译一个 Go 条码解码小工具，server.pl 调用该工具读取 latest.jpg 并输出码值
3. 使用云端药品识别/追溯接口，由 /api/medicine/scan 上传图片或码值查询
4. 后续如果需要药盒视觉识别，可接 RKNN 模型；条码识别本身不一定需要 RKNN
```

#### 已完成：AI 问诊对话界面优化

Go 原生 AI 页面已改成更接近对话终端的布局：

```text
左侧：用户档案、慢病、最新体征、药柜可用药
中间：AI 助手头像、助手气泡、用户气泡、AI 回复气泡、语音输入栏
右侧：常见咨询快捷问题和安全提示
```

已加入的动态表现：

```text
AI 状态为“思考中”时显示跳动输入点
麦克风区域保留“触摸录音”入口
常见咨询点击后仍调用 /api/ai/chat
安全提示去掉“联系家属”，改为“呼叫急救”
```

已在 HDMI 抓屏验证：

```text
hdmi-ai-final.png
AI 页面文字不再挤压右侧头像
右侧安全提示为“请立即就医或呼叫急救”
顶部时间为现实时间
```

#### 已完成：页面切换动画

Go UI 渲染流程已调整：

```text
先把当前页面绘制到离屏 image.RGBA
页面切换后的 260ms 内执行轻微右侧滑入
主循环 100ms 刷新一次，保证动画、扫描线、输入点可见
```

涉及页面：

```text
home
camera
ai
cabinet
```

#### 部署与验证命令

本轮重新编译：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\zykh_app\scripts\build_go_native_ui.ps1
```

推送：

```powershell
adb push .\zykh_app /userdata/
adb shell "chmod +x /userdata/zykh_app/bin/zykh-go-ui"
```

联网：

```sh
/userdata/medical_assistant/scripts/start_wifi.sh
```

时间校准：

```powershell
$utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')
adb shell "TZ=UTC date -s '$utc'"
```

后端启动：

```sh
cd /userdata/zykh_app
TZ=CST-8 AI_MODEL='deepseek-v4-flash' perl server.pl --daemon
```

启动 HDMI Go UI：

```sh
sh /userdata/zykh_app/scripts/start_go_hdmi_ui.sh
```

临时启动指定页面：

```sh
ZYKH_START_PAGE=camera sh /userdata/zykh_app/scripts/start_go_hdmi_ui.sh
ZYKH_START_PAGE=ai sh /userdata/zykh_app/scripts/start_go_hdmi_ui.sh
```

抓屏：

```sh
sh /userdata/zykh_app/scripts/capture_hdmi_screenshot.sh
```

#### 本轮最终验证状态

```text
Go native UI build: OK
ADB push: OK
Wi-Fi: connected, ssid=Tan, ip=192.168.43.59
API status time: 2026-06-02 23:17:42 北京时间
HDMI home screenshot: OK
HDMI camera screenshot: OK, realtime camera visible, about 8fps
HDMI AI screenshot: OK, chat-style UI visible
/api/medicine/scan: OK, demo-no-zbar fallback
```

### 第十三步：摄像头低延迟优化、964 Wi-Fi、北京时间与 AI 历史对话

#### 本轮需求

用户提出继续优化：

```text
1. 摄像头预览需要达到 25/30fps 水准，8fps 延迟太高，不利于识别
2. 时间需要改成北京时间
3. Wi-Fi 脚本改为连接 964，密码按用户提供值配置
4. AI 问诊要更像 ChatGPT，可上下翻看、保存历史对话
5. 整体 UI 需要更灵动，减少文字占位符，增加图标和动画
```

#### 摄像头预览优化

上一版问题：

```text
Go UI 通过后端 /api/camera/stream 获取 MJPEG
后端通过 GStreamer multifilesink 写临时 JPG 文件
Perl 再轮询最新 JPG 推流
HDMI 实测约 8fps，延迟偏高
```

本轮改为 Go UI 直连 GStreamer：

```text
Go UI 进入扫码页后直接启动 gst-launch-1.0
v4l2src 从 /dev/video5 取图
jpegenc 编码 JPEG
fdsink fd=1 将连续 JPEG 字节写到 stdout
Go UI 从 stdout 读取字节流
按 JPEG SOI/EOI 标记 FFD8...FFD9 切帧
Go UI 本地 jpeg.Decode 后绘制到预览区
```

关键变化：

```text
去掉后端 HTTP MJPEG 和磁盘临时 JPG 中转
Go UI 渲染主循环提高到 33ms，约 30Hz
摄像头帧写入改为 TryLock，拿不到 UI 锁就丢帧，不阻塞 GStreamer stdout
默认预览模式改为 640x360，目标 30fps
扫码按钮仍然会暂停实时预览，再调用 /api/medicine/scan 进行单次拍照识别
```

实测过程：

```text
640x480 直连后从 8fps 提升到约 24fps
640x360 曾出现高于 30fps 的读流结果
加入 videorate max-rate=30 后，在当前驱动状态下仍约 24fps
320x240 仍约 24fps
v4l2-ctl --set-parm=30 对 /dev/video5 不支持，返回 Inappropriate ioctl for device
```

继续排查：

```text
v4l2-ctl --list-ctrls 可见 exposure、vertical_blanking、analogue_gain 等控件
将 exposure 从 759 降到 200 后，帧率仍约 24fps
因此当前限制更像 sensor/driver/media pipeline 时序限制，不是 UI、JPEG 质量或分辨率瓶颈
```

当前结论：

```text
软件链路已从 8fps 高延迟轮询方案优化为低延迟直连方案
HDMI 稳定实测约 24fps，已经接近 25fps 水准
要稳定达到 30fps，需要继续从摄像头 sensor driver、media-ctl pipeline、设备树或可用 video 节点模式排查
```

本轮关键截图：

```text
hdmi-camera-fast2.png: 640x480 直连约 24fps，北京时间显示正确
hdmi-camera-320.png: 320x240 仍约 24fps
hdmi-camera-exposure200.png: exposure=200 后仍约 24fps
```

#### 北京时间修正

板子重启后系统时间再次回到：

```text
Thu Sep 28 00:30:22 UTC 2006
```

本轮处理：

```text
通过 adb 从电脑同步 UTC 时间到板子
Go UI 程序内强制 time.Local = Asia/Shanghai 固定 +08:00
start_go_hdmi_ui.sh 和 start_zykh_server.sh 继续保留 TZ=CST-8
```

验证：

```text
adb shell "TZ=UTC date -s '<PC UTC time>'; TZ=CST-8 date"
返回：Thu Jun 4 12:19:11 CST 2026
HDMI UI 显示：12:22、12:33，日期为 6月4日星期四
```

说明：

```text
仅设置 TZ 不能解决系统时间回到 2006 的问题。
后续如果要开机自动准确时间，需要 Wi-Fi 成功后执行网络校时，或给板子配置可用 RTC。
```

#### 964 Wi-Fi 脚本

新增脚本：

```text
zykh_app/scripts/start_wifi_964.sh
```

并已覆盖到板端常用路径：

```text
/userdata/medical_assistant/scripts/start_wifi.sh
```

脚本功能：

```text
生成 /userdata/wpa_964.conf
优先使用 wpa_passphrase
尝试 wlan0/wlan1
连接 SSID 964
DHCP 获取地址
写入 DNS
尝试 rdate 网络校时
```

本轮实际连接结果：

```text
扫描能看到 964
频段：2452 MHz，也就是 2.4GHz
信号：约 -86 dBm，偏弱
状态在 SCANNING / ASSOCIATING / DISCONNECTED 间循环
DHCP 未拿到租约
```

扫描结果关键行：

```text
44:f7:70:41:d7:00  2452  -86  [WPA2-PSK-CCMP][WPS][ESS]  964
```

当前判断：

```text
脚本已切到 964，但本次未连接成功。
优先检查热点距离、天线、密码是否正确、热点是否限制设备接入。
建议把 964 热点靠近板子，确认 2.4GHz WPA2-PSK，不隐藏 SSID，不开启 MAC 白名单。
```

#### AI 问诊界面与历史对话

Go UI 已将 AI 中间区域从单轮静态问答改为消息流：

```text
新增 aiMessage 结构：role / text / time
历史保存到 /userdata/zykh_app/data/ai-ui-history.json
最多保留最近 80 条消息
常见咨询点击后追加 user 消息和 assistant 回复
AI 思考中显示“正在输入”跳动点
麦克风录音完成后也写入一条历史记录
```

交互：

```text
触摸聊天区域上半部：向上翻历史
触摸聊天区域下半部：向下回到新消息
触摸麦克风按钮：录音
触摸右侧常见咨询：向 AI 发问
```

已验证截图：

```text
hdmi-ai-chat-history.png
```

#### UI 灵动化

本轮增加：

```text
首页服务按钮不再只用文字占位
开始取药：绘制药瓶/药片图标
测量体征：绘制心电图标
拍照识别：绘制相机图标
AI 麦克风按钮加入呼吸动画
页面仍保留滑入动效
扫码页保留扫描线动画
AI 思考中保留跳动点动画
```

说明：

```text
这些图标和动画均由 Go 原生绘制，不是 PNG 页面，也不依赖浏览器。
```

#### 当前部署状态

```text
Go native UI build: OK
ADB push: OK
Go HDMI UI: running
current page: home
time display: Beijing time
camera preview: direct GStreamer stdout JPEG stream
camera measured fps: stable about 24fps on current sensor/driver state
AI history file: /userdata/zykh_app/data/ai-ui-history.json
Wi-Fi script: /userdata/medical_assistant/scripts/start_wifi.sh now targets 964
964 connection: scanned but not associated successfully in this test
```

### 第十四步：Wi-Fi 图标、新热点、摄像头限帧与 AI 滑动手势

#### 本轮需求

```text
1. “网络正常”旁边增加可变 Wi-Fi 图标，根据连接状态和信号强弱变化
2. Wi-Fi 改连 LAPTOP-BSM79J69，密码按用户提供值配置
3. 摄像头预览需要限制帧率，避免过度卡顿，最好不要低于 15/20fps
4. AI 问诊历史需要支持手势上滑/下滑
5. 接入 GitHub 新仓库 Zykh-QSM，后续改动同步上去
```

#### Wi-Fi 图标

Go UI 新增 Wi-Fi 状态刷新：

```text
定期读取 wpa_cli status
定期读取 wpa_cli signal_poll
根据 wpa_state、ssid、RSSI 更新 UI
```

显示策略：

```text
COMPLETED：显示 Wi-Fi 图标
强信号：绿色
中/弱信号：橙色
未连接：红色
```

首页和子页面右上角已加入 Wi-Fi 图标。因为热点 SSID 较长，为避免压到时间，最终只显示强弱图标，不显示完整 SSID。

验证截图：

```text
hdmi-home-wifi-fixed.png
```

#### 新 Wi-Fi 热点

用户给出的热点为：

```text
LAPTOP-BSM79J69
```

板端扫描到的真实 SSID 为：

```text
LAPTOP-BSM79J69 1593
```

因此脚本已改为连接扫描到的真实 SSID：

```text
zykh_app/scripts/start_wifi_964.sh
/userdata/medical_assistant/scripts/start_wifi.sh
```

连接结果：

```text
wpa_state=COMPLETED
ssid=LAPTOP-BSM79J69 1593
ip_address=192.168.137.109
gateway=192.168.137.1
```

脚本修正：

```text
启动前删除 /var/run/wpa_supplicant/wlan0 残留控制文件
避免 wpa_supplicant 报 ctrl_iface exists
移除 rdate 自动校时，避免把北京时间写成 UTC 导致 UI 多加 8 小时
需要校时时继续用电脑通过 adb 写入 UTC 时间
```

#### 北京时间

本轮出现过一次网络校时后时间偏移：

```text
系统 UTC 被写成北京时间
Go UI 再按 +08:00 显示，导致页面显示 20:56
```

修正方式：

```text
取消 Wi-Fi 脚本中的 rdate 自动校时
继续使用 adb 从电脑设置 UTC 时间
Go UI 内部保持 Asia/Shanghai 显示
```

验证：

```text
adb shell "TZ=UTC date -s '<PC UTC time>'; TZ=CST-8 date"
返回：Thu Jun 4 12:58:39 CST 2026
HDMI 首页显示：12:59
```

#### 摄像头限帧

本轮调整：

```text
默认预览仍使用 Go UI 直连 GStreamer stdout JPEG
默认目标帧率改为 24fps
UI 主循环恢复为 33ms
FPS 统计按真实 elapsed 秒数折算，避免多秒累计误显示
```

中间测试：

```text
目标 20fps + 50ms UI 刷新时，实际只显示约 12fps，低于用户要求
恢复 24fps 目标后，体验更接近 20fps 以上
```

说明：

```text
当前摄像头链路的实际输出和 Go 绘制锁竞争会影响最终显示帧率。
如果继续卡顿，下一步应把摄像头帧缓存从 app 全局锁拆成独立 frame mutex，避免 render 持锁影响视频线程。
```

#### AI 手势滑动

AI 聊天区新增滑动手势：

```text
手指在聊天区向上滑：查看更早历史
手指在聊天区向下滑：返回较新的消息
保留原来的点击上半区/下半区翻页作为备用
```

实现变化：

```text
touchEvent 新增 StartX / StartY / DX / DY
触摸读取逻辑记录按下位置和松开位置
AI 页面根据 DY 判断上下滑动
```

#### GitHub 状态

当前本地 git remote：

```text
origin https://github.com/quectel-smart/QSM368ZP-WF.git
```

尝试查询：

```text
Donson/Zykh-QSM
```

结果：

```text
GitHub API 404 Not Found
```

结论：

```text
仅有仓库名 Zykh-QSM 不足以定位仓库，需要完整 owner/name 或仓库 URL。
拿到正确 URL 后，可把本地 remote 指向该仓库，再提交并推送当前 zykh_app 和调试记录。
```

### 第十五步：AI 流式对话、Wi-Fi 图标规则、药柜布局与 GitHub 仓库

#### GitHub 仓库

用户提供仓库：

```text
DonsonHH/Zykh-QSM
https://github.com/DonsonHH/Zykh-QSM
```

GitHub 插件确认：

```text
repository_full_name=DonsonHH/Zykh-QSM
visibility=private
permissions: admin/maintain/pull/push 均为 true
default_branch=main
```

本地新增 `.gitignore`，避免把以下内容推入仓库：

```text
.tools/
本地 HDMI 抓屏 PNG
临时日志
```

#### AI 问诊优化

本轮完成：

```text
Go UI 问诊接口从 /api/ai/chat 改为 /api/ai/chat/stream
读取 text/event-stream
解析 event: delta / done / error
收到 delta 后实时追加到助手气泡
助手状态从“思考中”切到“生成中”
done 后保存完整回复到 /userdata/zykh_app/data/ai-ui-history.json
```

接口验证：

```text
POST /api/ai/chat/stream
返回 event: meta
返回多个 event: delta
说明流式链路已打通
```

气泡显示优化：

```text
用户气泡和助手气泡宽度根据文字长度动态计算
短消息不再占满整行
长消息按行包裹
Markdown 做轻量清洗显示：去除 #、**、反引号，列表项转成适合终端显示的文本
```

手势方向修正：

```text
聊天区向下滑：查看更早历史
聊天区向上滑：回到更新消息
保留点击上半区/下半区翻页作为备用
```

#### Wi-Fi 图标规则

用户要求：

```text
强信号和中信号都显示绿色
弱信号才显示红色
```

当前规则：

```text
wpa_state != COMPLETED：红色
RSSI >= -75 dBm：绿色
RSSI < -75 dBm：红色
```

为了避免长 SSID 挤压时间，右上角只显示 Wi-Fi 图标，不显示 SSID 文本。

#### Wi-Fi 热点

用户提供：

```text
LAPTOP-BSM79J69
密码：<Wi-Fi密码>
```

板端扫描到的实际 SSID：

```text
LAPTOP-BSM79J69 1593
```

脚本已按实际 SSID 配置并验证成功：

```text
wpa_state=COMPLETED
ip_address=192.168.137.109
gateway=192.168.137.1
```

#### 摄像头限帧

本轮调整：

```text
默认预览目标改为 24fps
UI 刷新周期保持 33ms
修正 FPS 统计，按真实 elapsed 秒数计算，避免多秒累计误显示
```

说明：

```text
当前摄像头驱动实际输出会有波动。
若继续出现卡顿，下一步应把 cameraFrame 从 app 全局锁拆成独立锁，减少 UI 绘制对视频线程的影响。
```

#### 药柜 UI

首页：

```text
“更多”按钮向左移动，避免和“共23仓/正常/低/空”统计文字重叠。
```

药柜子页面：

```text
下半部分：8 个大仓，4 列 x 2 行
左上角：6 个中仓，2 列 x 3 行
右上角：9 个小仓，3 列 x 3 行
```

同时去掉大仓卡片里残留的尺寸文字，使卡片更干净。

验证截图：

```text
hdmi-home-final2.png
hdmi-cabinet-layout.png
hdmi-ai-stream-md.png
```

### 第十六步：TTS 播报与药品扫码解码

#### DeepSeek 能力边界

查询 DeepSeek 官方 API 文档后，当前项目可稳定使用的是文本 Chat Completions 和流式文本输出。

结论：

```text
DeepSeek 当前不作为本项目的 TTS 引擎
DeepSeek 当前不直接承担图片/条码视觉识别
DeepSeek 适合用于：
1. AI 问诊文本生成
2. 根据已解码出来的药品条码/溯源码做信息结构化补全
3. 结合老人档案、体征、病例记忆和药柜库存生成定制化问诊回复
```

#### TTS 播报接口

新增后端接口：

```text
POST /api/audio/speak
参数：text
```

实现策略：

```text
优先使用环境变量 TTS_CMD 指定的真实 TTS 命令
其次检测 espeak / flite
如果没有中文 TTS 引擎，则生成短提示音 WAV，并用 aplay 播放，验证喇叭链路
```

板端音频情况：

```text
存在 arecord
存在 aplay
存在 mpg123
存在 /dev/snd
声卡 0：rockchip,rk809-codec
声卡 1：rockchip_hdmi
```

本轮修复：

```text
aplay 默认设备会走 PulseAudio，报 Connection refused
已改为显式 ALSA 设备
默认播放设备：plughw:0,0
如需 HDMI 音频，可启动服务时设置 AUDIO_PLAY_DEVICE=plughw:1,0
```

验证结果：

```json
{
  "ok": true,
  "exit_code": 0,
  "mode": "notice-tone",
  "detail": "当前板端缺少中文 TTS 引擎，已用喇叭提示音验证播放链路；后续设置 TTS_CMD 可替换为真实语音合成。"
}
```

Go HDMI UI 已接入：

```text
AI 流式回复完成后自动调用 /api/audio/speak
底部麦克风/语音状态会显示播报状态
当前没有中文 TTS 引擎时，会提示“已验证喇叭播放；需接入中文 TTS 引擎”
```

后续真实中文 TTS 推荐路线：

```text
短期：外接一个 TTS_CMD 脚本，调用可用的云 TTS 或本地 TTS 二进制后播放 wav/mp3
中期：在板端集成 sherpa-onnx / piper / eSpeak NG 中文语音包
比赛演示：若只要求证明喇叭链路，当前 notice-tone 已可验证播放链路
```

#### 药品扫码解码

新增纯 Go 扫码工具：

```text
/userdata/zykh_app/bin/zykh-scan-code
源码：zykh_app/tools/scan-code
```

支持格式：

```text
QR Code
Data Matrix
Aztec
EAN-13 / EAN-8
UPC-A / UPC-E
Code128 / Code39 / Code93
ITF
```

后端扫码流程已调整为：

```text
POST /api/medicine/scan
1. 摄像头拍照生成 /userdata/zykh_app/web/camera/latest.jpg
2. 优先调用 zykh-scan-code -json 解码
3. 如果存在 zbarimg，则回退调用 zbarimg
4. 如果真实画面里没有码，则使用演示溯源码跑通查目录和自动录入链路
5. 查 medicine_catalog
6. 可继续调用 /api/medicine/auto_add 自动写入药柜
```

板端验证：

```text
/userdata/zykh_app/bin/zykh-scan-code -json /userdata/zykh_app/web/camera/latest.jpg
返回 {"ok":false,"error":"NotFoundException"}
```

说明当前摄像头画面里没有有效条码/二维码，不代表解码器不可用。

接口验证：

```json
{
  "ok": true,
  "scanner": "demo-no-zbar",
  "detail": "真实扫码未识别到条码/二维码：NotFoundException",
  "code": "TRACE6901234567890"
}
```

这说明：

```text
真实扫码工具已被后端调用
当前画面没有识别出码
系统回退到演示溯源码，继续完成本地药品目录查询流程
```

后续真实扫码测试方法：

```text
进入“拍照识别药品”页面
把药盒条形码、药品追溯码或二维码放在摄像头前
保持码面清晰、占画面宽度 1/3 到 1/2
点击“扫码识别”
如果本地 medicine_catalog 有对应 code / trace_code，会自动显示药名、批号、有效期并写入药柜
```

#### 时间校准

本轮发现板子重启后时间又回到 2006 年。已用电脑 UTC 时间校准，后端 `TZ=CST-8` 后返回北京时间：

```json
{
  "time": "2026-06-05 14:27:47"
}
```

后续每次重启板子后仍建议执行一次时间同步，否则 HTTPS 和 AI 接口可能受证书时间影响。
