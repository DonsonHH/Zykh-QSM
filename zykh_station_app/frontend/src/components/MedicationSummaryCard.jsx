import React, { useEffect, useState } from "react";
import { CalendarClock, Clock3, ScanFace, UsersRound } from "lucide-react";
import { formatClock, formatDay } from "../utils/time.js";

export function MedicationSummaryCard({ medication, identity, identityStatus, identityMessage }) {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <section className="card task-card medication-summary-card">
      <div className="home-time-panel">
        <div>
          <strong>{formatClock(now)}</strong>
          <span className="home-time-date">{formatDay(now)}</span>
        </div>
        <span className="home-time-icon" aria-hidden="true">
          <Clock3 size={42} />
        </span>
      </div>

      <div className="home-task-panel">
        <div className="card-heading compact">
          <span className="card-icon blue" aria-hidden="true">
            <CalendarClock size={30} strokeWidth={2.1} />
          </span>
          <div>
            <h2>今日用药</h2>
          </div>
          <span className={`home-current-user ${identityStatus}`} title={identityMessage}>
            <ScanFace size={18} aria-hidden="true" />
            {identity?.name || (identityStatus === "identifying" ? "确认中" : "未确认")}
          </span>
        </div>

        <div className="metric-grid" aria-label="今日用药摘要">
          <article>
            <span>待服药对象</span>
            <strong>{medication.pending_people ?? 0}<small>人</small></strong>
          </article>
          <article>
            <span>待执行</span>
            <strong>{medication.pending_plans ?? 0}<small>条</small></strong>
          </article>
          <article>
            <span>下次时间</span>
            <strong>{medication.next_time || "--:--"}</strong>
          </article>
        </div>

        <div className="next-dose">
          <span className="avatar" aria-hidden="true">
            <UsersRound size={26} strokeWidth={2.2} />
          </span>
          <div>
            <strong>
              下一条：{medication.featured_subject || "服务对象"} ·{" "}
              {medication.featured_medicine || "暂无计划"}
            </strong>
          </div>
        </div>
      </div>
    </section>
  );
}
