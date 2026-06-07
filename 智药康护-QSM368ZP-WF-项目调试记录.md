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

### 第十七步：摄像头卡顿、AI 气泡高度和 Wi-Fi 修复

#### 摄像头预览与扫码

用户反馈：

```text
摄像头对焦不稳定，扫不上码
摄像头画面卡顿
可以适当降低摄像头分辨率
```

板端排查：

```text
v4l2-ctl -d /dev/video5 --list-ctrls
```

结果：

```text
没有发现 autofocus / focus_absolute 等对焦控制项
可用控制项主要是 exposure、horizontal_flip、vertical_flip、analogue_gain
```

判断：

```text
当前摄像头更可能是固定焦距模组，软件侧不能直接调焦。
扫不上码时优先调整物距和光照：让码面清晰、无遮挡、占画面宽度 1/3 到 1/2。
```

本轮代码调整：

```text
Go HDMI UI 实时预览默认从 640x360@24fps 调低为 424x240@20fps
JPEG quality 从 70 降为 60，减少 Go 端 JPEG 解码压力
后端 HTTP 备用视频流也改为 424x240@20fps
扫码拍照仍单独使用较高分辨率，默认 1280x720，num-buffers=10
```

说明：

```text
预览低分辨率用于降低卡顿
扫码抓拍高分辨率用于保留条码细节
如果 1280x720 在某些情况下不稳定，可通过 CAMERA_CAPTURE_WIDTH / CAMERA_CAPTURE_HEIGHT 降回 640x480
```

已部署文件：

```text
/userdata/zykh_app/bin/zykh-go-ui
/userdata/zykh_app/server.pl
/userdata/zykh_app/scripts/start_go_hdmi_ui.sh
```

UI 启动日志：

```text
camera: 424x240@20
```

#### AI 问诊气泡和流式

用户反馈：

```text
气泡长度和高度没有随着文字多少变化
流式传输显示仍不理想
```

问题原因：

```text
旧逻辑中助手气泡最多只显示 4 行，用户气泡最多 3 行。
长回复会被截断，因此看起来高度不随内容增长。
```

本轮修复：

```text
助手气泡最多显示 9 行
用户气泡最多显示 6 行
气泡高度按实际行数动态计算
聊天区按可用高度从最新消息向上排布，避免长回复挤掉最新消息
Markdown 换行按段落单独换行，不再把所有段落粗暴拼成一个字符串
```

流式容错：

```text
如果 SSE 最后没有收到 done，但已经收到了 delta，UI 仍会把已有回复保存为一次完成回复。
避免网络中断或服务端提前断开时界面一直停在“生成中/中断”状态。
```

后端验证：

```text
POST /api/ai/chat/stream
返回 event: meta
随后连续返回多个 event: delta
```

说明流式后端链路正常，当前主要优化的是 Go UI 的显示和容错。

#### Wi-Fi 修复

用户反馈：

```text
Wi-Fi 连接好像有问题
```

排查发现：

```text
断网时默认路由落在 usb1
wpa_cli 没有看到 wlan0/wlan1 的 COMPLETED 状态
```

重新执行：

```text
/userdata/medical_assistant/scripts/start_wifi.sh
```

验证结果：

```text
wpa_state=COMPLETED
ssid=LAPTOP-BSM79J69 1593
ip_address=192.168.137.251
default route: wlan0 -> 192.168.137.1
RSSI=-55
internet=ok
```

本轮脚本改进：

```text
仓库版本不保存 Wi-Fi 密码
脚本从 WIFI_PASSWORD 或 /userdata/wifi_password.txt 读取密码
自动检查 wlan0 / wlan1
优先选择能扫描到目标 SSID 的无线网卡
连接后删除 usb0/usb1 默认路由，避免走错出口
追加 ping 测试输出 internet=ok / internet=fail
```

Go UI Wi-Fi 图标改进：

```text
不再只检查 wlan0
自动检查 wlan0 / wlan1，找到 COMPLETED 的接口后读取 SSID 和 RSSI
```

注意：

```text
/userdata/wifi_password.txt 是板端本地运行配置，不进入 Git 仓库。
```

### 第十八步：自动扫码交互与 Wi-Fi Watchdog

#### 摄像头文档处理

用户补充了摄像头驱动文档和 RKNN 文档。PDF 文件为加密 PDF，尝试空密码解密后仍需要 `cryptography` 支持才能完整提取文本；已安装临时依赖到工作区，但 `pypdf` 仍未稳定解出正文。

结合板端实际命令验证，本轮采用可直接验证的摄像头链路：

```text
v4l2-ctl -d /dev/video5 --list-ctrls
v4l2-ctl -d /dev/video5 --list-formats-ext
gst-launch-1.0 v4l2src device=/dev/video5 ...
```

关键结论：

```text
当前 /dev/video5 没有 autofocus / focus_absolute 控制项
摄像头更像固定焦距模组
扫码识别不建议走 RKNN，条码/二维码/溯源码应优先使用专用解码器
RKNN 后续更适合做药盒外观识别、药片/包装分类等视觉模型
```

#### 扫码交互重做

用户反馈：

```text
扫码识别、重新扫码、自动录入药柜三个按钮割裂，不符合实际使用流程
```

旧流程：

```text
用户点击扫码识别 -> 停预览 -> 拍照 -> 解码 -> 再点自动录入
```

问题：

```text
停预览和高分辨率拍照会造成明显卡顿
用户不知道什么时候识别到了码
自动录入缺少确认，容易误写药柜
```

新流程：

```text
进入摄像头页后自动扫描实时视频帧
每隔约 850ms 取一帧 JPEG 调用 /userdata/zykh_app/bin/zykh-scan-code
识别到码后暂停重复扫描
查询本地 medicine_catalog
弹窗显示药品名称、药品码、有效期
用户点击“录入药柜”后才调用 /api/medicine/auto_add
用户点击“取消”则忽略本次码并继续识别
```

摄像头页按钮改为：

```text
暂停识别 / 开始识别
清除结果
录入当前药品（只有识别到码后生效）
```

新 UI 状态：

```text
自动识别中
识别到码
目录查询中
目录未收录
正在录入药柜
已录入药柜
录入失败
```

说明：

```text
实时预览仍保持 424x240@20fps，避免显示卡顿
自动扫码直接使用实时帧，不再每次点击都强制停流拍照
如果码面太小或虚焦，仍需要调整物距、光照和码面占比
```

#### Wi-Fi 自动重连

新增脚本：

```text
/userdata/zykh_app/scripts/start_wifi_watchdog.sh
/userdata/zykh_app/scripts/ensure_wifi_watchdog.sh
```

逻辑：

```text
默认每 20 秒检查一次 Wi-Fi
检查 wlan0 / wlan1 是否 wpa_state=COMPLETED
再 ping 223.5.5.5 或网关
失败则自动调用 /userdata/medical_assistant/scripts/start_wifi.sh 重连
日志写入 /userdata/zykh_app/data/wifi-watchdog.log
```

`ensure_wifi_watchdog.sh` 使用 pidfile 管理：

```text
/userdata/zykh_app/data/wifi-watchdog.pid
```

并改用 `setsid` 启动，避免 ADB shell 退出时后台进程被清理。`start_go_hdmi_ui.sh` 已接入该启动器，每次启动 HDMI UI 时会自动确保 Wi-Fi watchdog 存在。

Wi-Fi 脚本进一步调整：

```text
SSID 从 WIFI_SSID 或 /userdata/wifi_ssid.txt 读取
密码从 WIFI_PASSWORD 或 /userdata/wifi_password.txt 读取
默认 SSID 为 964
DHCP 改为 -t 10 -T 3，并失败后再重试一次
拿到 IP 后按网段补默认网关
```

本轮现场验证：

```text
当前可扫描到 964，但扫描不到 LAPTOP-BSM79J69 1593
因此板端运行配置切换到 964
wpa_state=COMPLETED
ssid=964
ip_address=192.168.31.237
default route: 192.168.31.1 via wlan0
watchdog=running
ping 223.5.5.5 成功
ping 192.168.31.1 成功
```

注意：

```text
/userdata/wifi_ssid.txt 和 /userdata/wifi_password.txt 是板端本地运行配置，不进入 Git 仓库。
```

### 第十九步：Wi-Fi 多热点优先级、取药子界面和 RKNN 药盒识别入口

#### Wi-Fi Watchdog 与热点优先级

用户反馈：

```text
Wi-Fi watchdog 貌似没生效
尽量连接 LAPTOP-BSM79J69 1593
```

本轮排查：

```text
watchdog 进程存在，但板端运行配置之前只写了 964
因此 watchdog 只会反复连接 964，不会主动切换到 LAPTOP-BSM79J69 1593
```

脚本调整：

```text
/userdata/zykh_app/scripts/start_wifi_964.sh
```

改为多热点 profile 机制：

```text
优先读取 WIFI_SSID / WIFI_PASSWORD
其次读取 /userdata/wifi_profiles.conf
最后兼容 /userdata/wifi_ssid.txt 和 /userdata/wifi_password.txt
```

板端本地 profile 示例：

```text
LAPTOP-BSM79J69 1593|<密码>
964|<密码>
```

脚本行为：

```text
先扫描周围 SSID
按 profile 顺序优先尝试可见热点
LAPTOP-BSM79J69 1593 可见时优先连接
认证或 DHCP 失败时继续尝试下一个 profile
连接后清理旧默认路由，只保留当前无线接口的默认网关
```

现场验证：

```text
ssid=LAPTOP-BSM79J69 1593
wpa_state=COMPLETED
ip_address=192.168.137.66
default route: 192.168.137.1 via wlan0
ping 223.5.5.5 成功
```

说明：

```text
/userdata/wifi_profiles.conf 是板端本地配置，不进入 Git 仓库。
```

#### 开始取药子界面

用户要求：

```text
开始取药应该进入子界面
用户可自选药柜或药物
需要搜索功能
确认后打开对应药柜
```

旧逻辑：

```text
首页点击“开始取药”后直接按下一条计划调用 /api/dispense
```

新逻辑：

```text
首页点击“开始取药”进入 dispense 页面
左侧显示药品列表
右侧显示 23 个仓位按钮
顶部提供触屏筛选搜索：全部 / 降压 / 阿司匹林 / 二甲 / 低库存
用户可点药品或点仓位选择
点击确认后弹出确认框
确认后才调用 /api/dispense
```

库存保护：

```text
空仓不能取药
库存小于等于 0 不能取药
库存不足时确认按钮置灰，显示“库存不足，不能取药”
```

验证截图：

```text
hdmi-dispense-final.png
```

#### RKNN 药盒外观识别入口

用户提出：

```text
条码/二维码解码如果官方文档里找不到更好方案，可以做 RKNN 药盒外观识别
```

当前仓库 RKNN 示例：

```text
examples/rknn/rknn_yolov5_demo
examples/rknn/rknn_yolov8_pose_demo
examples/rknn/rknn_LPRNet_demo
examples/rknn/rknn_whisper_demo
```

结论：

```text
这些示例能证明 RKNN 运行链路
但没有药盒分类/检测模型
不能直接识别具体药盒名称
需要后续采集药盒图片数据，训练分类或检测模型，再转成 .rknn
```

本轮新增后端接口：

```text
POST /api/medicine/visual_recognize
```

行为：

```text
先拍摄当前摄像头图片
如果配置了 RKNN_MEDICINE_CMD，则调用该命令
命令可用 {image} 占位符接收图片路径
如果未配置，则返回 rknn-not-configured
```

接口验证结果：

```json
{
  "ok": true,
  "found": false,
  "source": "rknn-not-configured"
}
```

Go HDMI UI 摄像头页：

```text
第三个按钮在未识别到条码时显示“外观识别”
点击后调用 /api/medicine/visual_recognize
当前会提示未配置 RKNN 药盒模型
后续接入 RKNN_MEDICINE_CMD 后即可复用该入口
```

### 第二十步：药品入库三步向导、有效期 OCR 插拔口、摄像头限帧前移和触摸反馈

#### 用户新需求

```text
药品识别不再优先扫溯源码
流程改为：
1. 引导用户扫描商品条形码，用于读取完整药盒药品信息
2. 引导用户把药盒侧面有效期/保质日期面对摄像头识别，或人工确认
3. 引导用户确认药品信息，后端自动录入药柜

希望寻找 Hugging Face 上适合本板子的文字识别模型
摄像头仍存在严重卡顿，需要继续检查
整体 UI 可用，但触摸后缺少反馈，需要更像触控设备
```

#### Hugging Face OCR 模型结论

使用 Hugging Face 模型搜索查找：

```text
Chinese OCR ONNX mobile PP-OCR text recognition
Chinese OCR ONNX mobile text recognition
trocr ocr printed
```

结果：

```text
没有搜到可直接落地到 RK3568 Buildroot 的中文 OCR ONNX/mobile 模型包
TrOCR 类模型可以搜到，但主要是 Transformers/PyTorch，体积和运行时都不适合当前板子：
- 当前系统无 Python3 / pip3 / Node
- 没有 ONNX Runtime
- 没有现成 .rknn OCR 模型
- TrOCR 对英文/印刷文本更常见，不适合作为药盒中文有效期识别的板端首选
```

当前采用方案：

```text
后端预留 OCR_EXPIRY_CMD 插拔口
如果后续拿到 PaddleOCR/PP-OCR mobile、RKNN DBNet+CRNN、或其他板端可执行 OCR 命令，只需要设置 OCR_EXPIRY_CMD
UI 和数据库流程不需要重写
```

#### 后端新增接口

新增：

```text
POST /api/medicine/expiry_ocr
```

行为：

```text
1. 如果传入 manual_expire 或 expire_date，则尝试解析人工输入日期
2. 否则调用摄像头拍照，图片仍为 /userdata/zykh_app/web/camera/latest.jpg
3. 如果未配置 OCR_EXPIRY_CMD，返回 ok:true / found:false / source:ocr-not-configured
4. 如果配置了 OCR_EXPIRY_CMD，则用 {image} 替换当前图片路径并执行
5. 从 OCR 输出中解析 YYYY-MM-DD、YYYY/MM/DD、YYYY.MM.DD、YYYY年MM月DD日、YYYYMMDD、EXP/有效期至/保质期 等日期格式
```

板端验证：

```json
{
  "ok": true,
  "found": false,
  "source": "ocr-not-configured",
  "detail": "已拍摄药盒侧面，但当前未配置 OCR_EXPIRY_CMD。可先在确认页人工核对有效期，后续接入 PaddleOCR/PP-OCR 或 RKNN OCR 命令。"
}
```

自动录入接口增强：

```text
POST /api/medicine/auto_add
```

新增支持：

```text
expire_date 参数
```

说明：

```text
如果确认页带入 expire_date，则优先使用用户/OCR 确认的有效期写入 medicines 表
这样同一商品条形码不同批次有效期可以正确记录
```

#### Go HDMI UI 药品入库流程

摄像头页标题从：

```text
扫码识别药品 / 扫描药品溯源码
```

改为：

```text
录入药品 / 先扫商品条形码，再识别药盒侧面有效期，确认后自动写入药柜
```

新增三步状态：

```text
1 扫商品条形码
2 识别有效期
3 确认录入
```

交互逻辑：

```text
进入页面后默认处于 barcode 步骤
自动扫码只在 barcode 步骤运行
识别到商品条形码后：
  - 停止自动扫码
  - 查询 /api/medicine/lookup
  - 进入 expiry 步骤
  - 提示用户把药盒侧面有效期/保质期文字面对摄像头

点击“识别有效期”后：
  - 暂停实时预览
  - 调用 /api/medicine/expiry_ocr
  - 识别到日期则带入确认页
  - 未配置 OCR 或未识别到日期时，进入“待人工确认”

点击“跳过日期”：
  - 直接进入确认页
  - 有效期显示“待人工确认”

确认录入：
  - 调用 /api/medicine/auto_add
  - 带入 code、stock=1、expire_date
```

#### 摄像头卡顿优化

旧 GStreamer 直连 caps：

```text
video/x-raw,format=NV12,width=424,height=240
```

问题：

```text
Go 端虽然按 FPS sleep，但采集端没有 framerate caps
上游可能持续输出并堆积旧帧，表现为卡顿和延迟
```

新 caps：

```text
video/x-raw,format=NV12,width=424,height=240,framerate=20/1
```

说明：

```text
限帧前移到 v4l2src caps
Go 端仍保留最小帧间隔保护
这主要降低堆积延迟，不保证传感器本身一定能稳定 20/25/30fps
```

当前启动输出：

```text
camera: 424x240@20
```

如果后续仍只有 3-4fps：

```text
优先排查摄像头模组、光照、曝光时间、驱动 video 节点模式、media-ctl pipeline
也可以换摄像头模组验证是否为模组固定焦距/曝光导致
```

#### 触摸反馈

参考触控 UI 的常见做法：

```text
按钮需要有即时按压反馈
触摸目标应保持足够大，适老化界面至少接近 48dp 等级
```

当前实现：

```text
Go 原生 UI 在每次触摸事件处记录坐标
渲染层绘制 180ms 的半透明主色涟漪
不依赖浏览器、CSS 或组件库
首页、取药、摄像头、AI 问诊等页面都会获得统一触摸反馈
```

#### 本轮部署

部署到目标设备：

```text
adb -s ? push zykh_app\bin\zykh-go-ui /userdata/zykh_app/bin/zykh-go-ui
adb -s ? push zykh_app\server.pl /userdata/zykh_app/server.pl
adb -s ? shell "chmod +x /userdata/zykh_app/bin/zykh-go-ui; perl -c /userdata/zykh_app/server.pl"
```

板端验证：

```text
/userdata/zykh_app/server.pl syntax OK
ZYKH server daemon pid: 7109
Go HDMI UI started
pid: 7312
render: wayland
page: home
touch: /dev/input/event4
camera: 424x240@20
```

注意：

```text
本轮没有上传 GitHub
ADB 上有两个设备，其中 serial 为 ? 的设备才是 QSM368ZP-WF Buildroot 板子
后续 adb 命令必须显式使用 adb -s ?
```

### 第二十一步：商品条码实际操作、ShowAPI 条码查询、非 964 Wi-Fi 与 OCR 边界

#### 商品条码扫码功能是否已做

结论：

```text
已做。
Go HDMI UI 的“录入药品/拍照识别药品”页面会自动读取摄像头实时 JPEG 帧。
后台每隔一段时间取当前帧，调用 /userdata/zykh_app/bin/zykh-scan-code 解码。
zykh-scan-code 基于 Go gozxing，支持 EAN-13、EAN-8、UPC、Code128、Code39、二维码、DataMatrix 等。
药盒常见的 69 开头商品条形码属于 EAN-13，当前解码器支持。
```

现场操作方法：

```text
1. HDMI 触屏首页点击“拍照识别药品/录入药品”
2. 进入摄像头页面后，默认处于“1 扫商品条形码”
3. 把药盒上的 69 开头商品条形码放到画面中间
4. 建议距离摄像头 10-20cm，条码尽量横平竖直，保持清晰和充足光照
5. 识别到条码后，页面会自动进入“2 识别有效期”
6. 再把药盒侧面有效期/保质期文字面对摄像头，点击“识别有效期”
7. 如果 OCR 未配置或未识别到日期，可点击“跳过日期”，确认页会显示“待人工确认”
8. 最后在弹窗中确认药名、商品条码、有效期，然后录入药柜
```

UI 文案已补充：

```text
操作：将 69 开头商品条码放进画面中间，保持 10-20cm；识别后再把有效期那一侧对准摄像头。
```

#### ShowAPI 药品条码查询

用户提供接口：

```text
https://route.showapi.com/66-24?appKey={your_appKey}
content-type: application/x-www-form-urlencoded
POST body: code=6906618188014
```

实现方式：

```text
appKey 不写入 server.pl、Markdown、HTML、JS 或 Git
后端优先读取环境变量 SHOWAPI_APP_KEY
如果没有环境变量，则读取板端本地文件：
/userdata/zykh_app/data/showapi-app-key.txt
```

后端流程：

```text
lookup_medicine(code)
  1. 先查本地 medicine_catalog
  2. 如果本地没有，并且 code 是 69 开头 13 位商品条码，则调用 ShowAPI
  3. ShowAPI 返回成功后，把 name、spec、dosage、manuName、validity、approval、note 等整理为本地 medicine_catalog 记录
  4. 后续再扫同一个条码时优先走本地缓存，不重复依赖外网
```

新增/复用配置：

```text
SHOWAPI_APP_KEY
SHOWAPI_APP_KEY_FILE
/userdata/zykh_app/data/showapi-app-key.txt
```

板端验证：

```powershell
adb -s ? forward tcp:8080 tcp:8080
curl.exe -s "http://127.0.0.1:8080/api/medicine/lookup?code=6906618188014"
```

验证结果要点：

```json
{
  "ok": true,
  "found": true,
  "source": "showapi",
  "medicine": {
    "code": "6906618188014",
    "name": "皇后牌片仔癀珍珠膏",
    "manufacturer": "福建片仔癀化妆品有限公司",
    "dosage": "20g；早晚两次，洁肤后适量使用并略加按摩至皮肤吸收。"
  }
}
```

注意：

```text
通过 adb shell 直接 wget 输出中文时，Windows 端可能显示乱码。
这不是接口真实乱码。
用 adb forward 后在电脑 curl.exe 访问，中文正常。
```

#### Wi-Fi：不再使用 964

用户要求：

```text
注意别用 964 的 Wi-Fi
新增热点：名称为 emoji 热点，密码为用户提供值
```

处理：

```text
/userdata/wifi_profiles.conf 已改为只保留两个非 964 热点
start_wifi_964.sh 新增 WIFI_SKIP_SSIDS，默认跳过 964
即使 profile 文件中误留 964，也会被脚本过滤
```

板端本地 profile：

```text
LAPTOP-BSM79J69 1593|<密码>
emoji 热点|<密码>
```

脚本同步路径：

```text
/userdata/zykh_app/scripts/start_wifi_964.sh
/userdata/medical_assistant/scripts/start_wifi.sh
```

本轮还修复了特殊热点网关问题：

```text
之前脚本默认把网关猜成 x.x.x.1
emoji 热点 DHCP 实际可用网关为 10.209.211.193
脚本现在会尝试 DHCP 写入的 nameserver、x.x.x.1、x.x.x.193
并且只有 ping 223.5.5.5 成功才算 Wi-Fi 连接成功
只 ping 通网关不再算成功
```

板端验证：

```text
wpa_state=COMPLETED
ip_address=10.209.211.196
default route: 10.209.211.193 via wlan0
internet=ok
```

#### 轻量 OCR 说明

当前系统现实条件：

```text
Buildroot 2018.02-rc3
无 Python3 / pip3 / Node
无 ONNX Runtime
无 Tesseract
无现成 RKNN OCR 模型
Hugging Face 搜到的 TrOCR 类模型主要是 Transformers/PyTorch，不适合直接在当前板端运行
```

因此本轮没有假装实现“通用 OCR”。

已完成的工程接口：

```text
POST /api/medicine/expiry_ocr
OCR_EXPIRY_CMD
```

后续只要拿到一个板端可执行 OCR 命令，例如：

```text
OCR_EXPIRY_CMD='/userdata/zykh_app/bin/ocr-expiry {image}'
```

该命令输出 JSON 或文本，后端即可解析常见日期格式：

```text
YYYY-MM-DD
YYYY/MM/DD
YYYY.MM.DD
YYYY年MM月DD日
YYYYMMDD
EXP / 有效期至 / 保质期 + 日期
```

当前可用兜底：

```text
OCR 未配置或识别失败时，UI 进入“待人工确认”
用户仍可完成商品条码查询和药品录入
有效期后续可人工核对或通过 OCR 命令补齐
```

### 第二十二步：条码识别能力与摄像头画面质量验证

#### 用户现象

```text
用户已把药盒条码放到摄像头前，但 HDMI UI 没有扫出来。
用户另外用手机拍了一张较清晰的条码图片，希望确认是算法问题还是摄像头问题。
```

#### 手机清晰图验证

测试图片：

```text
C:/Users/Donson/Documents/WeChat Files/wxid_nzrjpu4f1bn112/FileStorage/Temp/513fff13a6d6413b0248aa0d2ef6a8e.jpg
```

电脑端用现有 Go 解码器测试：

```powershell
cd zykh_app/tools/scan-code
go run . -json "C:\Users\Donson\Documents\WeChat Files\wxid_nzrjpu4f1bn112\FileStorage\Temp\513fff13a6d6413b0248aa0d2ef6a8e.jpg"
```

结果：

```json
{
  "ok": true,
  "code": "6901070384745",
  "format": "EAN_13"
}
```

板端 arm64 二进制测试：

```powershell
adb -s ? push "C:\Users\Donson\Documents\WeChat Files\wxid_nzrjpu4f1bn112\FileStorage\Temp\513fff13a6d6413b0248aa0d2ef6a8e.jpg" /userdata/zykh_app/data/test-barcode-phone.jpg
adb -s ? shell "/userdata/zykh_app/bin/zykh-scan-code -json /userdata/zykh_app/data/test-barcode-phone.jpg"
```

结果：

```json
{
  "ok": true,
  "code": "6901070384745",
  "format": "EAN_13"
}
```

结论：

```text
条码解码算法没有问题。
板端 zykh-scan-code 也没有问题。
清晰 EAN-13 商品条码可以被识别。
```

#### 板端摄像头当前抓拍验证

执行：

```powershell
adb -s ? shell "wget -q -O - --post-data='' http://127.0.0.1:8080/api/camera/capture; echo; /userdata/zykh_app/bin/zykh-scan-code -json /userdata/zykh_app/web/camera/latest.jpg"
adb -s ? pull /userdata/zykh_app/web/camera/latest.jpg camera-latest-barcode-test.jpg
```

抓拍命令成功：

```json
{
  "ok": true,
  "image_url": "/camera/latest.jpg",
  "command": "gst-launch-1.0 -q v4l2src device='/dev/video5' num-buffers=10 ! video/x-raw,format=NV12,width=1280,height=720,framerate=30/1 ! videoconvert ! jpegenc ! filesink location='/userdata/zykh_app/web/camera/latest.jpg'"
}
```

但解码结果：

```json
{
  "ok": false,
  "error": "NotFoundException"
}
```

人工查看抓拍图：

```text
camera-latest-barcode-test.jpg
```

现象：

```text
画面中没有清晰、居中、足够大的药盒商品条码。
画面主要拍到了桌面/侧板/瓶身，条形码区域很小或不在有效位置。
前景物体也有明显虚焦/景深问题。
```

结论：

```text
当前无法扫出来主要不是算法问题，而是摄像头实际输入质量问题：
1. 条码没有在画面中心
2. 条码占画面比例太小
3. 摄像头可能固定焦距，近距离或斜面容易虚
4. 低分辨率实时流自动扫码比高清单帧更容易失败
```

现场建议：

```text
1. 在 HDMI 预览里确认条码确实出现在画面中间
2. 让条码尽量横平竖直，不要贴在弧面瓶身上
3. 条码宽度至少占画面宽度的 30%-60%
4. 距离摄像头从 10cm、15cm、20cm、25cm 逐步试，找到固定焦距清晰点
5. 增加正面光照，避免反光和阴影
6. 如果仍然无法在预览里看到清晰竖线，后续应更换自动对焦或更适合近距离扫码的摄像头模组
```

### 第二十三步：USB 自动对焦摄像头接入与 UVC 自动切换

#### 用户新动作

```text
用户通过 USB 接入了新的摄像头，认为该摄像头应支持自动调焦，希望替换旧摄像头并测试条码识别。
```

#### 板端识别结果

执行：

```powershell
adb -s ? shell "ls -l /dev/video*; v4l2-ctl --list-devices; lsusb; dmesg | tail"
```

发现：

```text
当前 /dev/video* 仍全部来自 Rockchip CSI/ISP：
- rkcif_mipi_lvds
- rkisp-vir0
- rkisp-vir1

当前 USB 设备中：
32d7:0001 = USB2IIC_CTP_CONTROL / wch.cn
这是触摸屏控制器，不是摄像头。
```

dmesg 里曾经出现过 USB 摄像头：

```text
usb 1-1: Product: FF Camera
usb 1-1: Manufacturer: FF Camera
uvcvideo: Found UVC 1.00 device FF Camera (32e6:9251)
```

但随后立刻断开：

```text
usb 1-1: USB disconnect
```

结论：

```text
新 USB 摄像头曾经被内核识别为 UVC 摄像头，说明 uvcvideo 驱动存在。
但当前摄像头已经从 USB 总线掉线，所以系统没有生成新的 /dev/video 节点。
当前程序无法实际切换到新摄像头，只能继续使用 /dev/video5。
```

可能原因：

```text
1. USB 摄像头/转接线接触不稳
2. USB 供电不足，摄像头枚举后掉线
3. 插到了不稳定的 OTG/Hub 口
4. 摄像头启动电流较大，板子 USB 口供电撑不住
```

现场建议：

```text
1. 重新插拔 USB 摄像头
2. 优先使用带外部供电的 USB Hub
3. 换一根短一点、质量更好的 USB 线
4. 插入后立刻执行：
   adb -s ? shell "lsusb; v4l2-ctl --list-devices; dmesg | tail -n 50"
5. 只要 v4l2-ctl --list-devices 出现 FF Camera 或 uvcvideo，并列出新的 /dev/videoX，就可以继续测试扫码
```

#### 本轮代码调整

为避免后续每次手动改设备号，已加入 UVC 自动优先逻辑。

Go HDMI UI 启动脚本：

```text
/userdata/zykh_app/scripts/start_go_hdmi_ui.sh
```

新增行为：

```text
启动时扫描 /dev/video*
如果 v4l2-ctl -d <dev> --all 显示 Driver name: uvcvideo，则认为是 USB 摄像头
优先设置：
ZYKH_CAMERA_DEVICE=<UVC 节点>
ZYKH_CAMERA_WIDTH=640
ZYKH_CAMERA_HEIGHT=480
ZYKH_CAMERA_FPS=30
ZYKH_CAMERA_QUALITY=75

如果没有 UVC 摄像头，则回退：
ZYKH_CAMERA_DEVICE=/dev/video5
ZYKH_CAMERA_WIDTH=424
ZYKH_CAMERA_HEIGHT=240
ZYKH_CAMERA_FPS=20
```

Go 原生 UI：

```text
旧 CSI 摄像头继续走 NV12 -> jpegenc
USB UVC 摄像头改走 image/jpeg -> jpegparse -> fdsink
```

Perl 后端：

```text
detect_camera_device() 优先查找 uvcvideo 设备
camera_capture_cmd() 对 UVC 使用 image/jpeg 管线
camera_stream_cmd() 对 UVC 使用 image/jpeg 管线
非 UVC 仍使用旧 NV12 管线
```

部署验证：

```text
/userdata/zykh_app/server.pl syntax OK
Go HDMI UI started
render: wayland
touch: /dev/input/event4
camera: /dev/video5 424x240@20
```

说明：

```text
当前仍显示 /dev/video5，代表 USB 摄像头没有在线。
当 USB 摄像头稳定枚举后，启动输出应变为类似：
camera: /dev/video23 640x480@30
```

### 第二十四步：更换 USB 接头后的摄像头复测

#### 用户新动作

```text
用户更换了一个 USB 接头后重新插入 USB 摄像头，希望再次识别设备并切换到新摄像头。
```

#### 当前板端复测结果

执行：

```powershell
adb -s ? shell "lsusb; v4l2-ctl --list-devices; ls -l /dev/video*"
adb -s ? shell 'for d in /sys/bus/usb/devices/*; do [ -f "$d/idVendor" ] || continue; echo device=$d vendor=$(cat $d/idVendor) product=$(cat $d/idProduct) name=$(cat $d/product 2>/dev/null) manufacturer=$(cat $d/manufacturer 2>/dev/null); done'
adb -s ? shell "dmesg | tail -n 260 | grep -Ei 'new .*usb|usb .*disconnect|uvcvideo|camera|idVendor|Product|Manufacturer|not accepting|unable to enumerate|device descriptor|over-current|reset high-speed|reset full-speed' || true"
```

结果：

```text
lsusb 当前仍只有：
- 2c7c:6005 Android
- 32d7:0001 USB2IIC_CTP_CONTROL / wch.cn
- 多个 Linux USB Host Controller

32d7:0001 是 HDMI 触摸屏控制器，不是摄像头。

v4l2-ctl --list-devices 当前仍只看到：
- rkcif_mipi_lvds
- rkisp-vir0
- rkisp-vir1

没有出现 FF Camera、uvcvideo 或新的 /dev/videoX。

dmesg 最近日志里也没有新的 USB 插入、断开、枚举失败、uvcvideo 事件。
```

结论：

```text
这次更换接头后，板端仍未检测到 USB 摄像头。
当前不是程序没切换，而是 USB 摄像头没有枚举进系统。
UVC 自动切换代码已经部署，但没有可用 UVC 节点时只能继续回退 /dev/video5。
```

下一步现场排查建议：

```text
1. 确认 USB 接头/转接头支持数据，不是仅充电线
2. 确认插入的是板子的 USB Host 口，不是设备/烧录/ADB 口
3. 尝试带外部供电的 USB Hub，避免摄像头上电后掉线
4. 插入摄像头后立刻执行：
   adb -s ? shell "dmesg | tail -n 80; lsusb; v4l2-ctl --list-devices"
5. 只有看到类似 “uvcvideo: Found UVC ...” 且 v4l2-ctl 列出新 /dev/videoX，才能继续测试新摄像头扫码
```

#### GitHub 代理配置

用户再次确认命令行可通过本机代理访问 GitHub：

```cmd
set HTTP_PROXY=http://127.0.0.1:7897
set HTTPS_PROXY=http://127.0.0.1:7897
set ALL_PROXY=socks5://127.0.0.1:7897
```

PowerShell 中使用等价写法：

```powershell
$env:HTTP_PROXY='http://127.0.0.1:7897'
$env:HTTPS_PROXY='http://127.0.0.1:7897'
$env:ALL_PROXY='socks5://127.0.0.1:7897'
```

### 第二十五步：回退老摄像头后的卡顿定位与 Go UI 优化

#### 用户新动作

```text
USB 新摄像头仍未被板端识别，因此先回退使用老摄像头。
用户反馈老摄像头画面卡、糊，同时怀疑可能不是摄像头本身，而是整个 Go UI 软件帧率不高。
用户要求核对当前调用方式是否与最早 GStreamer 调用一致。
```

#### 当前调用方式核对

最早验证可用的摄像头路线包括：

```sh
gst-launch-1.0 -q -e v4l2src device=/dev/video-camera0 num-buffers=1 \
  ! video/x-raw,format=NV12,width=640,height=480,framerate=30/1 \
  ! mppjpegenc \
  ! filesink location=/userdata/medical_assistant/camera/capture.jpg
```

以及 LVDS 直出预览：

```sh
gst-launch-1.0 -v v4l2src device=/dev/video-camera0 \
  ! video/x-raw,format=NV12,width=640,height=480,framerate=30/1 \
  ! videoconvert \
  ! waylandsink sync=false
```

本次检查发现，当前 Go UI 的摄像头预览不是 `waylandsink` 直出，而是：

```text
GStreamer 从 /dev/video5 取帧 -> JPEG 编码 -> stdout
Go 程序读取 JPEG -> Go 解码 -> 软件绘制到 1024x600 UI -> Wayland Blit
```

因此它比最早的 LVDS 直出多了 JPEG 解码、页面重绘和整屏提交，性能压力明显更大。

#### 纯摄像头基准测试

先停止 UI 和 GStreamer：

```powershell
adb -s ? shell "killall zykh-go-ui 2>/dev/null; killall gst-launch-1.0 2>/dev/null"
```

测试裸采集：

```powershell
adb -s ? shell "gst-launch-1.0 -v v4l2src device=/dev/video5 num-buffers=120 ! video/x-raw,format=NV12,width=640,height=480,framerate=30/1 ! fpsdisplaysink video-sink=fakesink text-overlay=false sync=false"
```

结果：

```text
640x480@30 裸采集平均约 21fps。
424x240@20 + jpegenc 平均也约 21fps。
mppjpegenc 可用，但编码器不改变摄像头裸采集上限。
临时设置 exposure=200 后，裸采集仍约 21fps。
```

结论：

```text
老 CSI 摄像头在当前驱动配置下，裸采集上限约 21fps。
它本身很难提供稳定 25/30fps。
画面糊更像是定焦距离、镜头质量、光照和条码摆放问题，不是条码解码算法失效。
```

#### Go UI 卡顿定位

首页空闲时测试：

```text
优化前 zykh-go-ui 在首页也能吃到约 106% CPU。
原因是主循环固定 33ms 整屏重绘一次，所有文字、卡片、图标和 Wayland Blit 都重复执行。
```

摄像头页优化前测试：

```text
摄像头页只有约 5-6fps。
zykh-go-ui 约 180% CPU。
gst-launch 只有约 6% CPU。
说明主要瓶颈不是 GStreamer，而是 Go UI 的 JPEG 解码、页面绘制、图像缩放和 Wayland 整屏提交。
```

#### 已完成优化

Go UI：

```text
1. 摄像头页和普通页面改成动态刷新率。
2. 首页、药柜、取药等静态页面加入页面缓存，避免重复重画文字和卡片。
3. 摄像头页拆成“静态背景缓存 + 实时视频区域覆盖”。
4. 摄像头图像缩放从逐像素浮点计算改为定点整数步进。
5. Wayland Blit 从逐字节 RGBA->BGRA 转换改为 32 位写入。
6. 日志增加 render_fps 和 render_avg_ms，便于后续持续判断 UI 性能。
7. 自动扫码间隔从 850ms 放宽到 1200ms，减少周期性卡顿。
```

摄像头链路：

```text
1. 老 CSI 摄像头默认回退为 /dev/video5。
2. 默认预览参数调整为 424x240@20，优先保证本地屏幕触控流畅。
3. 旧 CSI 摄像头的 Go 预览和后端拍照/流接口优先使用 mppjpegenc。
4. 如果后续 UVC 摄像头枚举成功，仍会自动切换到 UVC 的 MJPEG 640x480@30 路径。
```

后端：

```text
server.pl 的 camera_capture_cmd 和 camera_stream_cmd 已改为：
- UVC 摄像头：image/jpeg -> jpegparse
- 老 CSI 摄像头：NV12 -> mppjpegenc，若无 mppjpegenc 再回退 jpegenc
```

#### 当前复测结果

启动摄像头页：

```powershell
adb -s ? shell "ZYKH_START_PAGE=camera sh /userdata/zykh_app/scripts/start_go_hdmi_ui.sh"
```

当前输出：

```text
camera: /dev/video5 424x240@20
```

日志结果：

```text
摄像头页 render_fps 约 12-15fps。
render_avg_ms 约 33-48ms。
zykh-go-ui 约 100% CPU。
gst-launch 约 6% CPU。
自动扫码子进程会周期性产生额外 CPU 峰值。
```

结论：

```text
当前“整个软件卡”的主因已经确认是 Go/Wayland 软件渲染链路，而不是 GStreamer 编码。
经过优化后，摄像头页从 5-6fps 提升到约 12-15fps。
老摄像头裸采集上限约 21fps，Go UI 内嵌预览要稳定 20fps 仍比较困难。
如果必须稳定 20-30fps 并兼顾条码清晰度，建议继续解决 UVC 自动对焦摄像头枚举问题，或改成 GStreamer/Wayland 原生视频层叠加显示。
```

#### 当前部署状态

```text
板端已部署：
- /userdata/zykh_app/bin/zykh-go-ui
- /userdata/zykh_app/server.pl
- /userdata/zykh_app/scripts/start_go_hdmi_ui.sh

当前 UI 暂时停在摄像头页，便于现场观察画面流畅度。
```

### 第二十六步：体征测量子页面、MAX30102、GY-614 与喇叭接入

#### 用户新需求

```text
1. 如果 GitHub 推不上去，给出手动上传命令。
2. 继续把性能优化贯穿项目，特别是摄像头模糊、识别不到条形码和延迟问题。
3. 接入 MAX30102 心率血氧脚本：
   adb shell "perl /userdata/medical_assistant/scripts/read_max30102_vitals.pl"
4. 接入喇叭测试脚本：
   adb shell "SPK_VOL=230 sh /userdata/medical_assistant/scripts/play_beep.sh"
5. 增加体征测量子页面，显示测量结果。
6. 按 UART4 接入 GY-614 额温模块。
```

#### 本轮新增/更新文件

```text
zykh_app/server.pl
zykh_app/native/go-ui/main.go
zykh_app/bin/zykh-go-ui
zykh_app/scripts/read_max30102_vitals.pl
zykh_app/scripts/read_gy614_uart4.pl
zykh_app/scripts/play_beep.sh
智药康护-QSM368ZP-WF-项目调试记录.md
```

#### 板端部署路径

```text
/userdata/zykh_app/server.pl
/userdata/zykh_app/bin/zykh-go-ui
/userdata/medical_assistant/scripts/read_max30102_vitals.pl
/userdata/medical_assistant/scripts/read_gy614_uart4.pl
/userdata/medical_assistant/scripts/play_beep.sh
```

语法检查：

```text
/userdata/zykh_app/server.pl syntax OK
/userdata/medical_assistant/scripts/read_max30102_vitals.pl syntax OK
/userdata/medical_assistant/scripts/read_gy614_uart4.pl syntax OK
```

#### 后端新增接口

```text
POST /api/vitals/read
调用 MAX30102 脚本，读取心率/血氧，并写入 vitals_records。

POST /api/vitals/temp/read
调用 GY-614 UART4 脚本，读取额温，并写入 vitals_records。

POST /api/audio/beep
调用 play_beep.sh，默认 SPK_VOL=230。
```

#### 当前接口实测

喇叭：

```powershell
curl.exe -s -X POST http://127.0.0.1:8080/api/audio/beep
```

结果：

```json
{"volume":230,"ok":true,"exit_code":0,"detail":"喇叭提示音播放完成"}
```

额温：

```powershell
curl.exe -s -X POST http://127.0.0.1:8080/api/vitals/temp/read
```

结果：

```text
GY-614 /dev/ttyS4 已读取到有效帧。
body_temp_c 约 35.6
ambient_temp_c 约 25.5
```

心率血氧：

```powershell
curl.exe -s -X POST http://127.0.0.1:8080/api/vitals/read
```

结果：

```text
MAX30102 通信成功，max30102_connected=true。
本次未放稳手指，finger_detected=false。
脚本返回 quality=no_finger，说明硬件通信正常但没有有效脉搏信号。
测量时需要手指稳定覆盖传感器。
```

#### Go UI 新页面

首页“测量体征”现在进入子页面：

```text
page=vitals
```

页面包含：

```text
1. 心率/血氧卡片：触摸后调用 /api/vitals/read
2. 额温测量卡片：触摸后调用 /api/vitals/temp/read
3. 喇叭测试卡片：触摸后调用 /api/audio/beep
4. 最近记录区域：展示最新 vitals_records
```

UI 性能处理：

```text
vitals 页面纳入页面缓存。
只有测量状态、测量结果或历史记录变化时才重画。
测量调用在 goroutine 中执行，不阻塞触控主循环。
重复点击时通过 vitalsBusy 防止并发重复触发脚本。
```

#### 时间校准

板子曾回到 2000 年，已用电脑时间重新校准：

```powershell
$utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')
adb -s ? shell "TZ=UTC date -s '$utc'; hwclock -w 2>/dev/null || true; date"
```

服务接口当前返回北京时间：

```json
{"time":"2026-06-06 21:02:38"}
```

校时后重新读取 GY-614，数据库已写入北京时间记录：

```text
2026-06-06 21:05:43 / GY-614 / body_temp_c 35.7
```

#### 摄像头性能与条码识别建议

当前结论不变：

```text
老 CSI 摄像头裸采集上限约 21fps。
Go UI 内嵌预览经过优化后约 12-15fps。
条形码识别算法已验证可识别清晰手机照片中的 EAN-13 码。
实际摄像头扫不上更主要是画面糊、定焦距离、光照、条码占画面比例和 Go 解码/渲染延迟共同造成。
```

优先解决方案：

```text
1. 继续解决 UVC 自动对焦摄像头枚举问题，成功后走 MJPEG 640x480@30。
2. 条码识别时降低 UI 干扰：扫码页保持 424x240@20 预览，但抓拍识别可以单独用 640x480 或 1280x720 静态图。
3. 识别阶段尽量让条码横向占画面宽度 50%-80%，避免太近导致定焦虚焦。
4. 增加正面补光，减少反光。
5. 如果必须 20-30fps，可以考虑 GStreamer/Wayland 原生视频层叠加，不再让 Go 解码每一帧。
```

#### GitHub 手动上传命令

如果 Codex 无法写 Git 索引或推送，可以在 Windows PowerShell 中执行：

```powershell
cd C:\Users\Donson\.codex\worktrees\930c\QSM368WF

$env:HTTP_PROXY='http://127.0.0.1:7897'
$env:HTTPS_PROXY='http://127.0.0.1:7897'
$env:ALL_PROXY='socks5://127.0.0.1:7897'

git status --short
git add zykh_app/bin/zykh-go-ui `
        zykh_app/native/go-ui/main.go `
        zykh_app/server.pl `
        zykh_app/scripts/start_go_hdmi_ui.sh `
        zykh_app/scripts/read_max30102_vitals.pl `
        zykh_app/scripts/read_gy614_uart4.pl `
        zykh_app/scripts/play_beep.sh `
        "智药康护-QSM368ZP-WF-项目调试记录.md"

git commit -m "Add vitals measurement page and sensor integrations"
git push zykh main
```

如果 `zykh` remote 不存在：

```powershell
git remote add zykh https://github.com/DonsonHH/Zykh-QSM.git
git push -u zykh main
```

### 第二十五步：药品录入向导遮挡修复与流程强化

时间：2026-06-07

用户反馈：

```text
点击“识别有效期”后按钮会被遮挡，界面出错。
录药流程引导不清楚：什么时候扫码、什么时候扫码成功、什么时候拍有效期、是否跳过或人工输入、是否录入、录入到哪个柜子、打开哪个柜子。
```

修复方案：

```text
取消摄像头页旧版确认遮罩弹窗。
右侧固定显示“入库向导”，三步持续可见：
1 扫描商品条码
2 拍摄有效期
3 确认入柜开仓
```

底部操作按钮按步骤变化：

```text
条码阶段：暂停/开始扫条码、重新开始、等待条码
有效期阶段：重扫条码、跳过/人工填、识别有效期
确认阶段：重扫条码、取消录入、确认录入并开仓
```

录入逻辑：

```text
识别商品条码后自动进入有效期步骤。
有效期识别失败时可以跳过，标记为“待人工确认”。
确认录入成功后显示实际仓位，并调用 /api/dispense 触发对应仓位打开。
```

板端复测：

```text
camera: /dev/video23 800x600@30
render_fps=19~26
商品条码 6901070384745 已识别
页面进入第 2 步“拍摄有效期”
“识别有效期”按钮未被遮挡
```

实测截图：

```text
hdmi-camera-guide-final.png
```

### 第二十六步：AI 问诊、ASR、设置页与有效期修改优化

时间：2026-06-07

用户反馈：

```text
AI 问诊显示“AI 流式请求失败”。
麦克风语音输入显示“ASR 识别失败”。
AI 生成答案只显示 9 行，后面被省略。
主页右下角需要设置按钮，可调音量、网络、时间。
有效期识别后需要让用户确认；如果不对，可以用触摸方式修改日期。
```

修复内容：

```text
1. /api/ai/chat/stream 改为板端稳定 SSE：
   默认先用普通 AI 请求拿到完整回复，再按小段 delta 推给 UI。
   避免 Buildroot + openssl 直接解析上游流式响应时卡住。

2. Go UI 增加 AI fallback：
   如果流式失败或空回复，自动改用 /api/ai/chat 普通请求。
   旧历史里的 “AI 流式请求失败 / context deadline exceeded” 会被替换成“网络或 AI 接口响应超时，请重新发送问题”。

3. ASR 逻辑调整：
   录音成功但未识别到文本时，后端返回 ok:true、text:""。
   UI 显示“未听清，请靠近麦克风再按一次”，不再显示“ASR 识别失败”。
   zykh-ai-voice 修复 textCh 关闭后的等待问题，并扩大识别文本字段提取范围。

4. AI 回复长度控制：
   prompt 要求回答控制在 140-220 个中文字符，最多 4 条要点。
   Go UI 的 AI 气泡显示行数从 9 行提升到 18 行，减少省略。

5. 新增系统设置页：
   首页右下角新增“设置”按钮。
   设置页包含音量调节/测试、Wi-Fi 连接、北京时间微调。

6. 有效期确认修改：
   确认录入阶段显示 年-/年+、月-/月+、日-/日+。
   如果视觉识别有效期不对，用户可直接用触摸按钮修正日期后再确认录入。
```

板端复测：

```text
/api/audio/asr:
录音成功但无清晰语音时返回 ok:true, text:""，UI 不再报 ASR 失败。

/api/ai/chat:
普通 AI 请求返回 ok:true。

/api/ai/chat/stream:
短问题可连续输出 meta、delta、done。

Go UI:
设置页已显示音量、网络、北京时间模块。
AI 页旧内部错误已替换为可读提示。
```

### 第二十七步：TTS 中断、ASR 麦克风、气泡错位、药品入库和 Wi-Fi 修复

时间：2026-06-07

用户反馈：

```text
语音播报播放几秒后报 aplay pcm_write interrupted。
ASR 没生效，怀疑没识别到麦克风。
AI 问诊气泡文字有错位。
拍照识别有效期 OCR 报 JSON 错误，条码显示不全，有效期一直待人工确认。
自动录入没有判断盒子大小、没有录入数量，柜子状态仍显示空仓。
设置页 Wi-Fi 没连接到当前正确热点。
```

修复内容：

```text
1. TTS：
   原因是 /api/audio/speak 外层 timeout 只有 20 秒，Qwen TTS 生成耗时也计入其中，导致 aplay 播放长 WAV 时被 timeout 中断。
   timeout 提升到 90 秒，TTS 文本默认截断到 240 字，避免过长播报。

2. ASR：
   板端 arecord -l 显示 USB 摄像头自带麦克风为 card 1: FF Camera / USB Audio。
   record_audio 改为未显式配置 AUDIO_CAPTURE_DEVICE 时优先选择 USB Audio，即 plughw:1,0。
   录音采样率默认改为 8000Hz，匹配 fun-asr-flash-8k-realtime。

3. AI 气泡：
   限制单个助手气泡最大高度，按聊天窗口高度计算可显示行数，避免长回复挤出聊天区造成文字错位。

4. 有效期视觉识别：
   qwen3.6 有时返回带 think/Markdown 代码块的内容，parse_json_content 增强为优先提取 ```json {...}```，并清理 think 标签。
   当前画面只有条码没有日期时，接口返回 ok:true、found:false、need_user_confirm:true，不再报 JSON 失败。

5. 条码与录入：
   入库面板条码显示长度从 10 位限制改为 18 位，EAN-13 可完整显示。
   auto_add_medicine 新增盒型判断和数量估算：
     - 大盒优先 1-8 大仓
     - 中盒优先 18-23 中仓
     - 小盒优先 9-17 小仓
   stock 小于 1 时强制修正为 1。
   返回 box_size、slot_kind、stock。
   Go UI 确认页显示盒型/数量，并增加 年/月/日/数量 的触摸调节按钮。
   medBySlot 只把 stock>0 的记录显示为占仓，旧 stock=0 记录不再让柜子看起来仍为空或错误占用。

6. Wi-Fi：
   设置页连接 Wi-Fi 改为使用 /userdata/wifi_primary.conf 主热点文件。
   已在板端写入主热点配置文件。
   当前扫描结果没有发现 LAPTOP-BSM79J69 或 LAPTOP-BSM79J69 1593，因此无法实际连上该热点；此前脚本会回退到表情热点，现已避免自动回退。
```

板端复测：

```text
/api/audio/speak:
返回 ok:true, mode:qwen-tts, exit_code:0，未再出现 aplay pcm_write interrupted。

/api/audio/asr:
recording.device=plughw:1,0
recording.rate=8000
录音成功；现场无清晰语音时返回 text:""。

/api/medicine/expiry_vision:
ok:true, found:false
detail 表示当前画面仅有条码，未发现日期文字。

/api/medicine/auto_add:
返回 box_size=medium, slot_kind=中仓, stock=12。

Wi-Fi scan:
未扫描到 LAPTOP-BSM79J69 / LAPTOP-BSM79J69 1593。
```

### 第二十八步：Go UI 性能优化与 FF Camera 默认选择修复

时间：2026-06-07

用户反馈：

```text
Go UI 使用起来不跟手，摄像头页卡顿。
复测时发现误切到了老摄像头，应使用新 USB 摄像头 FF Camera。
```

修复内容：

```text
1. 渲染缓存：
   Go UI 增加 frameCache，避免每帧重新分配全屏 RGBA。
   AI 页面加入缓存键，非“思考中”状态不再每帧重画整页聊天记录。
   摄像头页拆成静态 UI 缓存和动态视频 overlay，静态缓存不再包含旧扫描线。

2. 局部刷新：
   renderSink 新增 BlitRect 能力。
   framebuffer、DRM、Wayland 三个显示后端均支持局部刷新。
   摄像头稳定预览时只刷新视频区域和状态条；toast、触摸反馈、页面切换仍整屏刷新。

3. 文本缓存：
   中文文本绘制增加位图缓存，最多保留 768 项。
   主页、AI、设置、药柜等文字密集页面减少重复 font.Drawer 绘制。

4. 摄像头性能：
   默认预览参数改为 640x480@30 采集、20fps UI 预览。
   摄像头帧过密时直接丢弃旧帧，只保留最新帧，避免延迟堆积。
   drawImageCover 改为直接操作 RGBA Pix 数组，减少 SetRGBA/RGBAAt 逐点调用开销。
   性能日志新增 camera_fps、camera_drop、jpeg_decode_avg_ms。

5. FF Camera：
   Go UI 直连 GStreamer 不再默认 /dev/video5。
   未设置 ZYKH_CAMERA_DEVICE 时，自动扫描 /dev/video*：
     - 优先设备名包含 FF Camera 且支持 MJPG 的节点
     - 其次任意 MJPG 30fps 摄像头
     - 最后才回退 /dev/video5
   启动时自动尝试 focus_automatic_continuous、focus_auto、auto_focus、continuous_auto_focus。
```

板端复测：

```text
v4l2-ctl --list-devices:
FF Camera: FF Camera (usb-xhci-hcd.0.auto-1)
  /dev/video23
  /dev/video24

Go UI 自动选择结果：
/userdata/zykh_app/data/camera-focus.txt
/dev/video23 focus_auto=1

摄像头页性能：
优化前老方案约 7-8fps，render_avg_ms 约 85-100ms。
局部刷新后约 11-13fps，render_avg_ms 约 34-56ms。
切到 FF Camera 并调整调度后约 15-20fps，render_avg_ms 约 29-41ms。
FF Camera JPEG 解码平均约 23-27ms，比老摄像头约 38ms 明显更快。
```
