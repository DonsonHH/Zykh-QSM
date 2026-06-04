# QSM368ZP-WF 本地浏览器组件集成建议

## 当前结论

当前基线没有集成浏览器组件，板端已经验证：

- HDMI 已连接，可用模式包含 `1024x600`、`1280x720`、`1920x1080`
- USB 触摸已识别：`wch.cn USB2IIC_CTP_CONTROL`
- Weston 可运行
- 未发现 `cog`、`chromium`、`qt5webengine`、`qmlscene`

所以显示链路没有问题，缺的是“网页运行壳”。

## 推荐路线

优先级：

1. `WPEWebKit + Cog + WPEBackend-fdo`
2. `WebKitGTK + MiniBrowser` 或自写 GTK WebView 壳
3. `Qt WebEngine`
4. 独立 Chromium

推荐第 1 种。原因：

- WPEWebKit 面向嵌入式设备和 kiosk 场景
- Cog 是 WPE 的轻量单窗口 launcher，适合直接全屏打开本地网页
- 依赖比 WebKitGTK 更少，不需要完整 GTK 桌面生态
- 当前板子已经有 Weston，适合用 `cog --platform=fdo`

WebKitGTK 可以作为备选，但它会引入 GTK、窗口系统、主题、字体等更多依赖，根文件系统更大。

## Buildroot 里优先查这些包

在 SDK 根目录执行：

```sh
grep -R "BR2_PACKAGE_COG\|BR2_PACKAGE_WPEWEBKIT\|BR2_PACKAGE_WPEBACKEND_FDO\|BR2_PACKAGE_WEBKITGTK\|BR2_PACKAGE_QT5WEBENGINE" \
  buildroot/package buildroot/.config 2>/dev/null
```

如果包存在，进入 Buildroot：

```sh
cd buildroot
make menuconfig
```

搜索并启用：

```text
BR2_PACKAGE_WESTON
BR2_PACKAGE_COG
BR2_PACKAGE_WPEWEBKIT
BR2_PACKAGE_WPEBACKEND_FDO
BR2_PACKAGE_CA_CERTIFICATES
BR2_PACKAGE_FONTCONFIG
```

建议同时加入中文字体和媒体能力：

```text
Noto CJK 或 WenQuanYi 字体
GStreamer 1.x
gst1-plugins-base
gst1-plugins-good
gst1-plugins-bad
gst1-libav
```

实际符号名以厂家 SDK 内的 Buildroot 版本为准。

## 如果 SDK 没有 WPEWebKit/Cog

当前板子系统是 Buildroot 2018.02-rc3，版本偏老。老 Buildroot 很可能没有现成的 WPEWebKit/Cog 包。

可选处理：

1. 让厂家提供带 WPEWebKit/Cog 的 rootfs 或 package 补丁
2. 从较新 Buildroot 回迁 `wpewebkit`、`cog`、`wpebackend-fdo`、`libwpe` 等 package
3. 改用厂家 SDK 已经支持的 `qt5webengine`
4. 换 Android/Ubuntu 镜像，用系统现成浏览器

最省时间的是第 1 种；最可控的是第 2 种；比赛/演示最稳的是第 4 种。

## 目标运行方式

启动 HDMI Weston：

```sh
sh /userdata/zykh_app/scripts/start_hdmi_weston.sh
```

启动智药康护后端：

```sh
sh /userdata/zykh_app/scripts/start_zykh_server.sh
```

启动本地网页壳：

```sh
export XDG_RUNTIME_DIR=/run
export WAYLAND_DISPLAY=wayland-0
cog --platform=fdo http://127.0.0.1:8080/
```

如果使用 Cog DRM 平台，不经过 Weston：

```sh
cog --platform=drm http://127.0.0.1:8080/
```

本项目当前更推荐先走 Weston + fdo，因为 HDMI 和触摸已经在 Weston 下识别过。

## 验证清单

烧录新镜像后，先确认：

```sh
which cog
which weston
ldd /usr/bin/cog
sh /userdata/zykh_app/scripts/check_display_stack.sh
```

再测显示：

```sh
sh /userdata/zykh_app/scripts/start_hdmi_weston.sh
export XDG_RUNTIME_DIR=/run
export WAYLAND_DISPLAY=wayland-0
cog --platform=fdo https://example.com
```

最后打开本地应用：

```sh
sh /userdata/zykh_app/scripts/start_zykh_server.sh
cog --platform=fdo http://127.0.0.1:8080/
```

如果中文乱码或方块：

- 缺中文字体
- 缺 fontconfig 缓存
- 需要加入 Noto CJK/WenQuanYi 并执行 `fc-cache`

如果 HTTPS 页面打不开：

- 缺 `ca-certificates`
- 系统时间不准

如果页面黑屏或非常卡：

- 查 EGL/GLES/Mesa/Panfrost/libmali 是否正确
- 用 `kmscube` 或 Weston EGL demo 先验证 GPU
- Cog 可先从 `--platform=fdo` 起步，减少 DRM 直连变量
