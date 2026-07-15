import React from "react";
import { HeartHandshake, ScanFace, Wifi } from "lucide-react";
import { StrokeDrawIcon } from "../components/StrokeDrawIcon.jsx";
import { formatClock, formatDay } from "../utils/time.js";

export function IdleScreen({ now, networkStatus, onWake }) {
  const online = Boolean(
    networkStatus?.wifi_connected ||
      networkStatus?.sim_connected ||
      networkStatus?.wifi?.connected ||
      networkStatus?.sim?.connected
  );
  return (
    <main className="idle-screen" id="main-content" onClick={onWake}>
      <div className="idle-brand">
        <span aria-hidden="true">
          <HeartHandshake size={38} strokeWidth={2.1} />
        </span>
        <div>
          <strong>智药康护终端</strong>
          <p>家庭康护与安全用药服务</p>
        </div>
      </div>

      <section className="idle-wake-area" aria-label="轻触唤醒终端">
        <div className="idle-time" aria-label="当前时间">
          <strong>{formatClock(now)}</strong>
          <span>{formatDay(now)}</span>
        </div>
        <button type="button" className="idle-wake-button">
          <StrokeDrawIcon icon={ScanFace} size={58} strokeWidth={2} mode="yoyo" active />
        </button>
        <h1>轻触屏幕开始使用</h1>
        <p>唤醒后将重新确认本次使用人</p>
      </section>

      <div className={`idle-network ${online ? "online" : "offline"}`}>
        <Wifi size={22} aria-hidden="true" />
        <span>{online ? "网络已连接" : "当前使用本地服务"}</span>
      </div>
    </main>
  );
}
