import React, { useEffect, useMemo, useState } from "react";
import { CalendarClock, Clock3, Fingerprint, UsersRound } from "lucide-react";
import { formatClock, formatDay } from "../utils/time.js";

export function MedicationSummaryCard({ medication, onQuickDispense, quickDispenseBusy = false }) {
  const [now, setNow] = useState(new Date());
  const plans = medication.plans?.length
    ? medication.plans
    : medication.featured_medicine
      ? [
          {
            id: "featured-plan",
            time: medication.next_time || "--:--",
            medicine: medication.featured_medicine,
            status: "待执行",
            target_user: medication.featured_subject || "家庭成员"
          }
        ]
      : [];

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const activePlan = useMemo(
    () => plans.find((plan) => plan.status === "待执行") || plans[0] || null,
    [plans]
  );

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

        {activePlan ? (
          <div className="home-dose-task" aria-label="下一条用药计划">
            <span className="avatar" aria-hidden="true">
              <UsersRound size={28} strokeWidth={2.2} />
            </span>
            <div className="home-dose-person">
              <strong>{activePlan.target_user} · {activePlan.time}</strong>
              <span>{activePlan.frequency_label || "每天"} · {activePlan.dose || "按说明"}</span>
            </div>
            <div className="home-dose-medicine">
              <strong>{activePlan.medicine}</strong>
              <span className={activePlan.status === "待执行" ? "pending" : "done"}>{activePlan.status}</span>
            </div>
            <button
              type="button"
              className="home-quick-dispense"
              disabled={activePlan.status !== "待执行" || quickDispenseBusy}
              onClick={() => onQuickDispense?.(activePlan)}
            >
              <Fingerprint size={22} aria-hidden="true" />
              {quickDispenseBusy ? "读取中" : "一键取药"}
            </button>
          </div>
        ) : (
          <div className="home-dose-empty">今日暂无用药计划</div>
        )}
      </div>
    </section>
  );
}
