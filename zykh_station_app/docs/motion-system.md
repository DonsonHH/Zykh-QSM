# 终端动效系统

## 原则

- 默认使用静态 Lucide 图标，不再加载 Lottie 播放器或动画 JSON。
- 动效直接复用 Lucide 的原始 SVG 路径，不替换原有静态图形。
- 品牌 Logo 使用一次描边；进行中的测量、扫码、录音和分析允许正向/反向往复描边。
- 业务状态结束后移除动画状态，最终图形与原静态图标完全一致。
- 动效不用来表达唯一信息，不阻断任何触摸操作。
- 系统开启“减少动态效果”时直接显示静态图标。

## 接入白名单

当前只允许以下位置使用 `StrokeDrawIcon`：

```text
components/TopBar.jsx          品牌 Logo
components/InquiryChatStep.jsx 录音中的麦克风、分析中的助手
pages/IdleScreen.jsx           息屏页中央唤醒图标
pages/Scan.jsx                 扫码核验进行状态
pages/Vitals.jsx               测量中的额温与指尖引导
```

首页快捷入口、网络、导航、返回、结果、同步、成功和告警图标全部保持静态。

## 实现

```text
frontend/src/components/StrokeDrawIcon.jsx
frontend/src/styles/stroke-draw.css
frontend/scripts/test-motion-contract.mjs
```

`StrokeDrawIcon` 在渲染前为 Lucide 的几何节点设置归一化 `pathLength=1`。`once` 模式逐段将 `stroke-dashoffset` 从 `1` 绘制到 `0`；`yoyo` 模式使用同一时间轴正向绘制、反向收回。`active=false` 或任务组件卸载时会取消动画并恢复完整静态描边。

顶部品牌 Logo 启用 `replayOnPointer`：初次显示播放一次，之后每次屏幕 `pointerdown` 都取消旧实例并从头播放一次。该监听不阻止点击，也不改变原操作目标。

所有路径绘制不允许在页面内单独覆盖速度。统一时序为：单向阶段 `1600ms`、正反完整周期 `3200ms`、单段描边 `900ms`。组件会根据 SVG 路径数量自动计算错峰时间，因此麦克风、助手、扫码、额温和指纹图标的完整周期一致。

体征结果区使用 SVG 轨道与圆角弧段，弧段长度、偏移和旋转采用同一个 `3200ms` 非线性周期；中心心脏只做轻微缩放。息屏背景属于低对比度环境动效，使用 `6400ms` 单向呼吸阶段；二者均为装饰效果，不承载状态信息。

## 检查

```bash
cd zykh_station_app/frontend
npm run test:motion
npm run build
```

测试会阻止白名单外的动效接入、旧 `MotionIcon`/`lottie-web` 回流，以及无法随业务状态停止或未回到完整静态描边的动画。
