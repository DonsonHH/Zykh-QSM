import React from "react";
import { HeartHandshake } from "lucide-react";
import { StatusChip } from "./StatusChip.jsx";
import { formatClock, formatDay } from "../utils/time.js";

export function TopBar({ site, chips, now }) {
  return (
    <header className="top-bar">
      <div className="brand-block">
        <div className="brand-mark" aria-hidden="true">
          <HeartHandshake size={34} strokeWidth={2.2} />
        </div>
        <div>
          <h1>智药康护终端</h1>
          <p>
            {site?.station_name || "偏远社区康护站"} · {site?.service_name || "村镇智慧用药服务点"}
          </p>
        </div>
      </div>

      <div className="clock-block" aria-live="polite">
        <strong>{formatClock(now)}</strong>
        <span>{formatDay(now)}</span>
      </div>

      <div className="status-row" aria-label="系统状态">
        {(chips || []).map((chip) => (
          <StatusChip key={chip.id} chip={chip} />
        ))}
      </div>
    </header>
  );
}
