import React from "react";
import { HeartHandshake } from "lucide-react";
import { BrandLogoImage } from "../components/BrandLogoImage.jsx";
import { NetworkStatusIcons } from "../components/NetworkStatusIcons.jsx";
import { StrokeDrawIcon } from "../components/StrokeDrawIcon.jsx";
import { formatClock, formatDay } from "../utils/time.js";

export function IdleScreen({ now, networkStatus, onWake }) {
  return (
    <main className="idle-screen" id="main-content" onClick={onWake}>
      <div className="idle-brand">
        <span aria-hidden="true">
          <BrandLogoImage size={64} />
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
          <span className="idle-wake-glyph" aria-hidden="true">
            <HeartHandshake className="idle-wake-glyph-ghost" size={150} strokeWidth={1.9} />
            <StrokeDrawIcon icon={HeartHandshake} size={150} strokeWidth={1.9} mode="yoyo" pace="idle" active />
          </span>
        </button>
        <h1>轻触屏幕开始使用</h1>
      </section>

      <NetworkStatusIcons networkStatus={networkStatus} variant="idle" />
    </main>
  );
}
