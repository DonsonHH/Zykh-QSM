# 智药康护板端系统

这是给 QSM368ZP-WF Buildroot 系统使用的轻量前后端原型。

板子当前没有 `python3`、`pip3`、`node`，因此本系统使用：

- Perl 单文件 HTTP 后端：`server.pl`
- 静态前端：`web/`
- SQLite 数据库：`data/zykh.db`

## 部署

在 Windows PowerShell 中执行：

```powershell
cd C:\Users\Donson\Documents\QSM368WF
adb push .\zykh_app /userdata/
adb shell "chmod +x /userdata/zykh_app/server.pl"
adb shell "cd /userdata/zykh_app && nohup perl server.pl > server.log 2>&1 &"
adb forward tcp:8080 tcp:8080
```

然后在电脑浏览器打开：

```text
http://127.0.0.1:8080
```

默认首页是适老化终端前台界面，原来的管理/调试界面保留在：

```text
http://127.0.0.1:8080/admin.html
```

摄像头大屏预览和 AI 问诊页面：

```text
http://127.0.0.1:8080/camera.html
http://127.0.0.1:8080/consult.html
```

首页是给老人直接使用的 16:9 触屏终端：大时钟、下次服药、开始取药、测量体征、拍照识别药品、AI 问诊、药柜状态和系统状态。药柜总数为 23 仓，首页展示摘要，点“更多”进入 `/cabinet.html` 查看完整布局：8 个大仓、6 个中仓、9 个小仓。后台只用于设备、药品和 GPIO 等调试设置。

## 板子原生展示前端

当前已新增一条不依赖浏览器的 Go 原生 UI 路线：

- 源码：`native/go-ui/`
- 编译脚本：`scripts/build_go_native_ui.ps1`
- 板端启动：`scripts/start_go_hdmi_ui.sh`
- 板端停止：`scripts/stop_go_hdmi_ui.sh`

Go 原生 UI 直接写 `/dev/fb0`，默认读取 `/dev/input/event4` 触摸事件，并通过本机 Perl 后端 API 读取 SQLite 里的用药计划、药柜状态等数据。它不是网页截图，也不需要 Chromium/Cog。

Windows 交叉编译：

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

当前 Buildroot 不是 Ubuntu/Debian，不能用 `apt install chromium`。如果只用板子接 HDMI 触屏本地运行，有三条路线：

1. 推荐：在 SDK/Buildroot 里加入 `wpewebkit` + `cog`，用 Cog 做全屏 kiosk 浏览器壳。
2. 备选：加入 `qt5webengine`，它基于 Chromium 内核但体积和编译成本更高。
3. 不推荐直接移植独立 Chromium：Buildroot 主线通常不是以桌面 Chromium 包的方式提供，依赖、GPU/Wayland 和内存成本都更高。

当前板子已确认：

- HDMI 已连接：`/sys/class/drm/card0-HDMI-A-1/status = connected`
- HDMI 可用模式包含 `1024x600`、`1280x720`、`1920x1080`
- 触摸模块已识别：`wch.cn USB2IIC_CTP_CONTROL`
- 已有 Weston：`/usr/bin/weston`
- 暂无本地浏览器壳：未发现 `cog`、`chromium`、`qt5webengine`

所以现阶段 HDMI 链路是通的，但网页前端不能直接在板子上打开。要本地显示完整前端，必须给系统补浏览器壳。

详细集成建议见：`docs/browser-integration.md`。

临时启动 HDMI/Weston：

```sh
sh /userdata/zykh_app/scripts/start_hdmi_weston.sh
```

启动智药康护后端：

```sh
sh /userdata/zykh_app/scripts/start_zykh_server.sh
```

检查 HDMI、触摸和浏览器环境：

```sh
sh /userdata/zykh_app/scripts/check_display_stack.sh
```

先在 SDK 里查包：

```sh
grep -R "BR2_PACKAGE_COG\|BR2_PACKAGE_WPEWEBKIT\|BR2_PACKAGE_QT5WEBENGINE" buildroot/package buildroot/.config 2>/dev/null
```

如果有 Cog，目标启动方式类似：

```sh
export XDG_RUNTIME_DIR=/run
export WAYLAND_DISPLAY=wayland-0
cog --platform=fdo http://127.0.0.1:8080/
```

如果使用 DRM 平台：

```sh
cog --platform=drm http://127.0.0.1:8080/
```

实际平台参数取决于 SDK 里启用的是 Wayland/Weston 还是 DRM/KMS。触屏需要同时确认 `libinput`/evdev 输入设备已进入显示栈。

## 停止服务

```powershell
adb shell "ps | grep server.pl"
adb shell "pkill -f /userdata/zykh_app/server.pl"
```

如果系统没有 `pkill`，用 `kill PID`。

## 默认硬件映射

默认 `1号仓` 会输出 `GPIO27` 500ms 控制脉冲，用来验证出药链路。

可通过环境变量改映射：

```sh
SLOT1_GPIO=27 SLOT2_GPIO=65 perl server.pl
```

真实电机或舵机不要直接接 GPIO，应使用驱动板或 PWM 控制板，外部供电并与开发板共地。

## 摄像头拍照

前台“识别”按钮会调用：

```text
POST /api/camera/capture
```

默认尝试用 `/dev/video-camera0` 和 GStreamer 拍一张图到 `web/camera/latest.jpg`。如果你们已有稳定的摄像头调用命令，可以用环境变量覆盖，`{out}` 会替换为输出图片路径：

```sh
CAMERA_CAPTURE_CMD='你的拍照命令 --output {out}' perl server.pl --daemon
```

首页“拍照识别药品”会优先尝试浏览器 `BarcodeDetector` 识别条形码、二维码或 DataMatrix 溯源码。识别到码后调用本地药品目录：

```text
GET /api/medicine/lookup?code=6901234567890
POST /api/medicine/auto_add
```

`medicine_catalog` 表保存条码/溯源码、药名、规格、厂家、批号、有效期等信息。识别成功后会自动写入 `medicines` 药柜表，并记录 `medicine_auto_add`。当前内置 3 条演示目录，后续可以批量导入真实药品目录，或接 zbar/RKNN/企业追溯接口。

`/camera.html` 使用浏览器可直接显示的 MJPEG 视频流：

```text
GET /api/camera/stream?width=640&height=480&fps=30
```

后端会启动 GStreamer 连续抓帧，并按 `multipart/x-mixed-replace` 推给浏览器。当前板子验证 `/dev/video5` 可用，所以服务会优先使用 `/dev/video5`；也可以手动覆盖：

```sh
CAMERA_DEVICE=/dev/video5 CAMERA_STREAM_FPS=30 perl server.pl --daemon
```

暂停预览或拍照识别前会调用：

```text
POST /api/camera/stream/stop
```

这样摄像头会释放给拍照识别接口使用。这个方案不再切换到 HDMI/LVDS 的 Wayland 全屏预览，画面都在浏览器内完成。

## 摄像头屏幕预览

前台“打开预览”按钮会调用：

```text
POST /api/camera/preview/start
```

默认命令使用当前板子可用的 Wayland/GStreamer 预览链路：

```sh
echo 'output:LVDS-1:primary' > /tmp/.weston_drm.conf
export XDG_RUNTIME_DIR=/run
export WAYLAND_DISPLAY=wayland-0
gst-launch-1.0 -v v4l2src device=/dev/video-camera0 ! video/x-raw,format=NV12,width=640,height=480,framerate=30/1 ! videoconvert ! waylandsink sync=false
```

服务会自动检测显示输出，优先使用 `HDMI-A-1`，没接 HDMI 时回退 `LVDS-1`。也可以手动指定：

```sh
CAMERA_OUTPUT=HDMI-A-1 perl server.pl --daemon
```

如果后续摄像头预览命令变化，可覆盖：

```sh
CAMERA_PREVIEW_CMD='gst-launch-1.0 ... waylandsink sync=false' perl server.pl --daemon
```

## AI 问诊

`/consult.html` 是 AI 问诊对话套壳。麦克风输入和喇叭播报由浏览器的 Web Speech API 完成；后端只负责代理大模型接口，避免 API Key 暴露在前端。

默认已按 DeepSeek 的 OpenAI 兼容接口配置。启动服务时可以用环境变量传 Key：

```sh
AI_API_KEY='你的key' AI_MODEL='deepseek-v4-flash' perl server.pl --daemon
```

也可以把 Key 放到板子本地文件，避免每次启动都在命令行里带密钥：

```sh
echo '你的key' > /userdata/zykh_app/data/ai-api-key.txt
chmod 600 /userdata/zykh_app/data/ai-api-key.txt
AI_MODEL='deepseek-v4-flash' perl server.pl --daemon
```

如需显式指定 DeepSeek 地址：

```sh
AI_API_BASE='https://api.deepseek.com/chat/completions' AI_API_KEY='你的key' AI_MODEL='deepseek-v4-flash' perl server.pl --daemon
```

不要把 API Key 写入前端文件。前端只访问 `/api/ai/chat`，Key 只存在后端环境变量或 `/userdata/zykh_app/data/ai-api-key.txt`。

当前 Buildroot 的 `wget` 不支持 HTTPS，后端已改为用 `openssl s_client` 直接发送 HTTPS POST，并处理 DeepSeek 的 `Transfer-Encoding: chunked` 响应。

### 定制化上下文

问诊页会维护老人档案、最近体征和药柜库存，后端会在每次请求时自动写入 system prompt：

```text
GET/POST /api/profile
GET/POST /api/vitals
GET/POST /api/memories
POST /api/ai/chat
POST /api/ai/chat/stream
```

`health_memories` 表用于按时间保存病例、随访、护理备注、异常体征等长期记忆。AI 问诊时会自动带入最近病例记忆、最近体征和药柜库存。

`/api/ai/chat/stream` 使用 `text/event-stream` 返回：

```text
event: delta
data: {"delta":"..."}
```

前端会边收到边显示，最后自动播报完整回答。AI 会被明确告知它只能做健康知识解释、用药提醒和就医建议，不能替代医生诊断，不能因为药柜里有某种药就建议用户自行服用。

## Wi-Fi 联网

板子上已有 `wpa_supplicant`、`wpa_passphrase`、`wpa_cli`、`udhcpc`。连接热点的基本流程：

```sh
wpa_passphrase '964' '你的Wi-Fi密码' > /userdata/wpa_964.conf
killall wpa_supplicant 2>/dev/null
mkdir -p /var/run/wpa_supplicant
ifconfig wlan0 up
wpa_supplicant -B -i wlan0 -c /userdata/wpa_964.conf -C /var/run/wpa_supplicant
sleep 8
wpa_cli -i wlan0 -p /var/run/wpa_supplicant status
udhcpc -i wlan0 -q -n
ifconfig wlan0
```

如果 `wlan0` 一直是 `NO-CARRIER` 或 `SCANNING`，改用 `wlan1` 重试。热点建议先开 2.4GHz、WPA2-PSK，避免 5GHz、WPA3 或隐藏 SSID。

联网成功后测试 DNS/路由：

```sh
ping -c 3 api.deepseek.com
```

如果 `wget https://api.deepseek.com` 报错，不一定是网络失败；当前板子的 `wget` 本身不支持 HTTPS。
