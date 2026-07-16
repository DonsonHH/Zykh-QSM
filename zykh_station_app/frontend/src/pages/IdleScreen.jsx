import React from "react";
import { BellRing, HeartHandshake, Pill } from "lucide-react";
import { BrandLogoImage } from "../components/BrandLogoImage.jsx";
import { NetworkStatusIcons } from "../components/NetworkStatusIcons.jsx";
import { StrokeDrawIcon } from "../components/StrokeDrawIcon.jsx";
import { formatClock, formatDay } from "../utils/time.js";
import { getMedicationReminder } from "../utils/medicationReminder.js";

export function IdleScreen({ now, networkStatus, medication, onWake }) {
  const reminder = getMedicationReminder(medication, now);

  return (
    <main className={`idle-screen ${reminder ? "has-medication-reminder" : ""}`} id="main-content" onClick={onWake}>
      <div className="idle-brand">
        <span aria-hidden="true">
          <BrandLogoImage size={64} />
        </span>
        <div>
          <strong>智药康护终端</strong>
        </div>
      </div>

      <section className="idle-wake-area" aria-label={reminder ? "用药时间提醒" : "轻触唤醒终端"}>
        <div className="idle-time" aria-label="当前时间">
          <strong>{formatClock(now)}</strong>
          <span>{formatDay(now)}</span>
        </div>
        {reminder ? (
          <div className="idle-medication-reminder" aria-live="polite">
            <span className="idle-reminder-icon" aria-hidden="true"><BellRing size={36} /><Pill size={62} /></span>
            <p>{reminder.plan.target_user}，{reminder.state === "soon" ? "快到用药时间了" : "该取药了"}</p>
            <strong>{reminder.plan.medicine}</strong>
            <span>{reminder.plan.time} · {reminder.plan.dose || "按说明"}</span>
            <small>轻触屏幕进入一键取药</small>
          </div>
        ) : (
          <>
            <button type="button" className="idle-wake-button">
              <StrokeDrawIcon
                icon={HeartHandshake}
                size={160}
                strokeWidth={1.9}
                className="idle-wake-glyph"
                mode="yoyo"
                pace="idle"
                active
              />
            </button>
            <h1>轻触屏幕开始使用</h1>
          </>
        )}
      </section>

      <NetworkStatusIcons networkStatus={networkStatus} variant="idle" />
    </main>
  );
}
