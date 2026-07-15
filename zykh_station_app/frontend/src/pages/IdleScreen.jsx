import React from "react";
import { HeartHandshake, ScanFace, Signal, SignalLow, Wifi, WifiOff } from "lucide-react";
import { StrokeDrawIcon } from "../components/StrokeDrawIcon.jsx";
import { formatClock, formatDay } from "../utils/time.js";
import { getNetworkIndicators } from "../utils/network.js";

export function IdleScreen({ now, networkStatus, onWake }) {
  const { localMode, wifi, sim } = getNetworkIndicators(networkStatus);
  return (
    <main className="idle-screen" id="main-content" onClick={onWake}>
      <div className="idle-brand">
        <span aria-hidden="true">
          <HeartHandshake size={38} strokeWidth={2.1} />
        </span>
        <div>
          <strong>智药康护终端</strong>
        </div>
      </div>

      <section className="idle-wake-area" aria-label="轻触唤醒终端">
        <div className="idle-time" aria-label="当前时间">
          <strong>{formatClock(now)}</strong>
          <span>{formatDay(now)}</span>
        </div>
        <button type="button" className="idle-wake-button">
          <StrokeDrawIcon icon={ScanFace} size={88} strokeWidth={1.9} mode="yoyo" active />
        </button>
        <h1>轻触屏幕开始使用</h1>
      </section>

      <div className={`idle-network ${localMode ? "local" : ""}`} role="group" aria-label="网络状态">
        <span className={`idle-network-item ${wifi.tone}`} aria-label={wifi.label} title={wifi.label}>
          {wifi.connected ? <Wifi size={24} aria-hidden="true" /> : <WifiOff size={24} aria-hidden="true" />}
          <b>WiFi</b>
        </span>
        <span className={`idle-network-item ${sim.tone}`} aria-label={sim.label} title={sim.label}>
          {sim.tone === "good" ? <Signal size={24} aria-hidden="true" /> : <SignalLow size={24} aria-hidden="true" />}
          <b>SIM</b>
        </span>
      </div>
    </main>
  );
}
