import React from "react";
import { HeartHandshake, Signal, SignalLow, SlidersHorizontal, Wifi, WifiOff } from "lucide-react";
import { formatClock, formatDay } from "../utils/time.js";
import { getNetworkIndicators } from "../utils/network.js";
import { StrokeDrawIcon } from "./StrokeDrawIcon.jsx";

export function TopBar({ networkStatus, now, page, onOpenSystemCheck }) {
  const { localMode, wifi, sim } = getNetworkIndicators(networkStatus);
  const showHeaderClock = page !== "home";
  const dayText = formatDay(now);
  const [dateText, weekText = ""] = dayText.split(/(?=星期)/);

  return (
    <header className={`top-bar ${showHeaderClock ? "with-clock" : "home-top"}`}>
      <div className="brand-block">
        <div className="brand-mark" aria-hidden="true">
          <StrokeDrawIcon icon={HeartHandshake} size={38} strokeWidth={2.1} replayOnPointer />
        </div>
        <div>
          <h1>智药康护终端</h1>
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
        <div className={`network-cluster ${localMode ? "offline local-only" : ""}`} role="group" aria-label="网络状态">
          <div className={`mini-network ${wifi.tone}`} aria-label={wifi.label} title={wifi.label}>
            {wifi.connected ? <Wifi size={24} aria-hidden="true" /> : <WifiOff size={24} aria-hidden="true" />}
            <span>WiFi</span>
          </div>
          <div className={`mini-network ${sim.tone}`} aria-label={sim.label} title={sim.label}>
            {sim.tone === "good" ? <Signal size={24} aria-hidden="true" /> : <SignalLow size={24} aria-hidden="true" />}
            <span>SIM</span>
          </div>
        </div>
        <button className="system-check-button" type="button" onClick={onOpenSystemCheck} aria-label="打开设置">
          <SlidersHorizontal size={24} aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}
