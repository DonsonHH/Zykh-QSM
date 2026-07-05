import React from "react";
import { HeartHandshake, Signal, SignalLow, SlidersHorizontal, Wifi, WifiOff } from "lucide-react";
import { formatClock, formatDay } from "../utils/time.js";

export function TopBar({ site, networkStatus, now, page, onOpenSystemCheck }) {
  const wifiConnected = Boolean(networkStatus?.wifi_connected);
  const wifiSignal = networkStatus?.wifi_signal || (wifiConnected ? "good" : "none");
  const simConnected = Boolean(networkStatus?.sim_connected);
  const simPresent = Boolean(networkStatus?.sim_present);
  const simSignal = networkStatus?.sim_signal || (simConnected ? "good" : simPresent ? "weak" : "none");
  const localMode = networkStatus?.mode === "local" || (!wifiConnected && !simConnected);
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
          <div className={`mini-network ${wifiSignal === "good" ? "good" : wifiConnected ? "weak" : "offline"}`}>
            {wifiConnected ? <Wifi size={22} aria-hidden="true" /> : <WifiOff size={22} aria-hidden="true" />}
            <span>WiFi</span>
            <strong>{wifiConnected ? "已连接" : "未连接"}</strong>
          </div>
          <div className={`mini-network ${simSignal === "good" ? "good" : simPresent ? "weak" : "offline"}`}>
            {simSignal === "good" ? <Signal size={22} aria-hidden="true" /> : <SignalLow size={22} aria-hidden="true" />}
            <span>SIM</span>
            <strong>{simConnected ? "可用" : simPresent ? "待连接" : "未检测"}</strong>
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
