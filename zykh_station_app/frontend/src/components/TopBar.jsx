import React from "react";
import {
  SlidersHorizontal
} from "lucide-react";
import { formatClock, formatDay } from "../utils/time.js";
import { BrandLogoImage } from "./BrandLogoImage.jsx";
import { NetworkStatusIcons } from "./NetworkStatusIcons.jsx";

export function TopBar({ networkStatus, now, onOpenSystemCheck }) {
  const dayText = formatDay(now);
  const [dateText, weekText = ""] = dayText.split(/(?=星期)/);

  return (
    <header className="top-bar with-clock">
      <div className="brand-block">
        <div className="brand-mark" aria-hidden="true">
          <BrandLogoImage size={68} />
        </div>
        <div>
          <h1>智药康护终端</h1>
        </div>
      </div>

      <div className="status-controls">
        <div className="clock-block compact" aria-live="polite">
          <strong>{formatClock(now)}</strong>
          <span className="date-line">{dateText}</span>
          <span className="weekday-line">{weekText}</span>
        </div>
        <NetworkStatusIcons networkStatus={networkStatus} />
        <button className="system-check-button" type="button" onClick={onOpenSystemCheck} aria-label="打开设置">
          <SlidersHorizontal size={24} aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}
