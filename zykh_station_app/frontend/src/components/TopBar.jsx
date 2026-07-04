import React from "react";
import { HeartHandshake, SlidersHorizontal } from "lucide-react";
import { StatusChip } from "./StatusChip.jsx";
import { formatClock, formatDay } from "../utils/time.js";

export function TopBar({ site, chips, now, onOpenSystemCheck }) {
  return (
    <header className="top-bar">
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

      <div className="clock-block" aria-live="polite">
        <strong>{formatClock(now)}</strong>
        <span>{formatDay(now)}</span>
      </div>

      <div className="status-controls">
        <div className="status-row" aria-label="系统状态">
          {(chips || []).map((chip) => (
            <StatusChip key={chip.id} chip={chip} />
          ))}
        </div>
        <button className="system-check-button" type="button" onClick={onOpenSystemCheck} aria-label="打开系统检查">
          <SlidersHorizontal size={24} aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}
