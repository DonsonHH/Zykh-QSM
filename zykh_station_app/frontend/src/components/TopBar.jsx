import React from "react";
import {
  HeartHandshake,
  SignalHigh,
  SignalLow,
  SignalMedium,
  SignalZero,
  SlidersHorizontal,
  Wifi,
  WifiHigh,
  WifiLow,
  WifiOff,
  WifiZero
} from "lucide-react";
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
            <WifiStrength connected={wifi.connected} bars={wifi.bars} />
            <span>WiFi</span>
          </div>
          <div className={`mini-network ${sim.tone}`} aria-label={sim.label} title={sim.label}>
            <SimStrength connected={sim.connected} bars={sim.bars} />
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

function WifiStrength({ connected, bars }) {
  if (!connected) {
    return <WifiOff size={24} aria-hidden="true" />;
  }
  if (bars === 0) {
    return <WifiZero size={24} aria-hidden="true" />;
  }
  if (bars === 1) {
    return <WifiLow size={24} aria-hidden="true" />;
  }
  return bars >= 4 ? <Wifi size={24} aria-hidden="true" /> : <WifiHigh size={24} aria-hidden="true" />;
}

function SimStrength({ connected, bars }) {
  if (!connected || bars === 0) {
    return <SignalZero size={24} aria-hidden="true" />;
  }
  if (bars === 1) {
    return <SignalLow size={24} aria-hidden="true" />;
  }
  if (bars === 2) {
    return <SignalMedium size={24} aria-hidden="true" />;
  }
  return <SignalHigh size={24} aria-hidden="true" />;
}
