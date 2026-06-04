# 智药康护 Go 原生 HDMI UI

这个目录是无浏览器方案的 Go 原生 UI。它不使用 Chromium、Cog、Qt WebEngine，也不使用网页截图或 PNG 中转。

运行方式：

- Weston 负责保持 HDMI 桌面输出
- Go 程序连接 `/run/wayland-0`
- Go 程序创建 Wayland 全屏窗口并绘制原生 UI
- DRM/KMS 和 `/dev/fb0` 只作为备用调试路径，不再作为 HDMI 主显示方案
- 触摸默认读取 `/dev/input/event4`
- 数据通过本机 Perl 后端 API 读取 `http://127.0.0.1:8080`
- 字体使用 `/userdata/zykh_app/fonts/simhei.ttf`

## 当前页面

- 首页：时间、下次服药、开始取药、测量体征、拍照识别、AI 问诊入口、药柜摘要
- 药柜页：23 仓布局，8 个大仓、9 个小仓、6 个中仓
- AI 页：第一版占位页，后续接麦克风输入和语音播报

## 交叉编译

在 Windows 安装 Go 后执行：

```powershell
cd C:\Users\Donson\Documents\QSM368WF\zykh_app\native\go-ui
go mod tidy
New-Item -ItemType Directory -Force ..\..\bin
$env:GOOS = "linux"
$env:GOARCH = "arm64"
$env:CGO_ENABLED = "0"
go build -trimpath -ldflags="-s -w" -o ..\..\bin\zykh-go-ui .
```

推送到板子：

```powershell
cd C:\Users\Donson\Documents\QSM368WF
adb push .\zykh_app /userdata/
adb shell "chmod +x /userdata/zykh_app/bin/zykh-go-ui /userdata/zykh_app/scripts/*.sh"
```

启动：

```sh
sh /userdata/zykh_app/scripts/start_go_hdmi_ui.sh
```

停止：

```sh
sh /userdata/zykh_app/scripts/stop_go_hdmi_ui.sh
```

## 环境变量

```sh
ZYKH_RENDER_TARGET=wayland
XDG_RUNTIME_DIR=/run
WAYLAND_DISPLAY=wayland-0
ZYKH_DRM_CARD=/dev/dri/card0
ZYKH_FB=/dev/fb0
ZYKH_TOUCH_EVENT=/dev/input/event4
ZYKH_UI_WIDTH=1024
ZYKH_UI_HEIGHT=600
ZYKH_API_BASE=http://127.0.0.1:8080
ZYKH_FONT=/userdata/zykh_app/fonts/simhei.ttf
```

## 后续扩展

- AI 问诊页接入语音输入和 TTS
- 摄像头页后续需要用 Go 侧直接接入摄像头帧或独立 DRM plane，避免回到浏览器/截图中转
- 条码/溯源码识别应移到后端或本地 zbar/RKNN，避免依赖浏览器 BarcodeDetector
- 可加入长按、返回手势、触摸校准和启动自恢复
