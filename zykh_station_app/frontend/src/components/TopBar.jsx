import React from "react";
import { HeartHandshake, Signal, SignalLow, SlidersHorizontal, Wifi, WifiOff } from "lucide-react";
import { formatClock, formatDay } from "../utils/time.js";

export function TopBar({ site, networkStatus, now, page, onOpenSystemCheck }) {
  const wifiConnected = Boolean(networkStatus?.wifi_connected);
  const wifiSignal = networkStatus?.wifi_signal || (wifiConnected ? "good" : "none");
  const simConnected = Boolean(networkStatus?.sim_connected);
  const simPresent = Boolean(networkStatus?.sim_present);
  const simSignal = networkStatus?.sim_signal || (simConnected ? "good" : simPresent ? "weak" : "none");
  const explicitLocalMode = networkStatus?.mode === "local";
  const localMode = explicitLocalMode || (!wifiConnected && !simConnected);
  const displayWifiConnected = explicitLocalMode ? false : wifiConnected;
  const displayWifiSignal = explicitLocalMode ? "none" : wifiSignal;
  const displaySimConnected = explicitLocalMode ? false : simConnected;
  const displaySimPresent = explicitLocalMode ? false : simPresent;
  const displaySimSignal = explicitLocalMode ? "none" : simSignal;
  const showHeaderClock = page !== "home";
  const dayText = formatDay(now);
  const [dateText, weekText = ""] = dayText.split(/(?=星期)/);

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
            <span className="date-line">{dateText}</span>
            <span className="weekday-line">{weekText}</span>
          </div>
        ) : null}
        <div className={`network-cluster ${localMode ? "offline" : ""}`} aria-label="网络状态">
          <div className={`mini-network ${displayWifiSignal === "good" ? "good" : displayWifiConnected ? "weak" : "offline"}`}>
            {displayWifiConnected ? <Wifi size={22} aria-hidden="true" /> : <WifiOff size={22} aria-hidden="true" />}
            <span>WiFi</span>
            <strong>{explicitLocalMode ? "未使用" : displayWifiConnected ? "已连接" : "未连接"}</strong>
          </div>
          <div className={`mini-network ${displaySimSignal === "good" ? "good" : displaySimPresent ? "weak" : "offline"}`}>
            {displaySimSignal === "good" ? <Signal size={22} aria-hidden="true" /> : <SignalLow size={22} aria-hidden="true" />}
            <span>SIM</span>
            <strong>{explicitLocalMode ? "未使用" : displaySimConnected ? "可用" : displaySimPresent ? "待连接" : "未检测"}</strong>
          </div>
          {localMode ? <em>本地模式</em> : null}
        </div>
        <button className="system-check-button" type="button" onClick={onOpenSystemCheck} aria-label="打开设置">
          <SlidersHorizontal size={24} aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}
