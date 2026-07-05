import React from "react";
import { HeartHandshake, Signal, SignalLow, SlidersHorizontal, WifiOff } from "lucide-react";
import { formatClock, formatDay } from "../utils/time.js";

export function TopBar({ site, networkStatus, now, page, onOpenSystemCheck }) {
  const signal = networkStatus?.signal || networkStatus?.status || "weak";
  const isGood = signal === "good";
  const isOffline = signal === "none" || networkStatus?.mode === "local";
  const NetworkIcon = isOffline ? WifiOff : isGood ? Signal : SignalLow;
  const label = isOffline ? "本地兜底" : networkStatus?.label || "SIM网络";
  const statusText = isGood ? "信号良好" : isOffline ? "无网本地" : "正在检测";
  const showHeaderClock = page !== "home";

  return (
    <header className={`top-bar ${showHeaderClock ? "with-clock" : "home-top"}`}>
      <div className="brand-block">
        <div className="brand-mark" aria-hidden="true">
          <HeartHandshake size={34} strokeWidth={2.2} />
        </div>
        <div>
          <h1>智药康护终端</h1>
          <p>
            {site?.station_name || "智药康护家用终端"} · {site?.service_name || "偏远家庭弱网用药服务"}
          </p>
        </div>
      </div>

      <div className="status-controls">
        {showHeaderClock ? (
          <div className="clock-block compact" aria-live="polite">
            <strong>{formatClock(now)}</strong>
            <span>{formatDay(now)}</span>
          </div>
        ) : null}
        <div className={`network-indicator ${isGood ? "good" : isOffline ? "offline" : "weak"}`} aria-label={`网络状态：${label}`}>
          <NetworkIcon size={28} aria-hidden="true" />
          <span>{label}</span>
          <strong>{statusText}</strong>
        </div>
        <button className="system-check-button" type="button" onClick={onOpenSystemCheck} aria-label="打开系统检查">
          <SlidersHorizontal size={24} aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}
