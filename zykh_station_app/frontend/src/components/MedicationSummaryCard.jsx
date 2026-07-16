import React, { useEffect, useState } from "react";
import { CalendarClock, Clock3, UsersRound } from "lucide-react";
import { formatClock, formatDay } from "../utils/time.js";

const PLAN_ROTATION_MS = 4500;

export function MedicationSummaryCard({ medication }) {
  const [now, setNow] = useState(new Date());
  const [planIndex, setPlanIndex] = useState(0);
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

  useEffect(() => {
    setPlanIndex(0);
  }, [plans.map((plan) => plan.id).join("|")]);

  useEffect(() => {
    if (plans.length < 2) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      setPlanIndex((current) => (current + 1) % plans.length);
    }, PLAN_ROTATION_MS);
    return () => window.clearInterval(timer);
  }, [plans.length]);

  const activePlan = plans[planIndex] || null;

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

        <div className="next-dose" aria-label="今日用药计划轮播">
          <span className="avatar" aria-hidden="true">
            <UsersRound size={26} strokeWidth={2.2} />
          </span>
          <div className="next-dose-viewport" aria-hidden="true">
            <div className="next-dose-track" style={{ "--plan-offset": `${planIndex * -48}px` }}>
              {plans.map((plan) => (
                <article className="next-dose-item" key={plan.id}>
                  <strong>{plan.target_user} · {plan.time}</strong>
                  <span>{plan.medicine} · {plan.status}</span>
                </article>
              ))}
            </div>
          </div>
          <span className="screen-reader-only" aria-live="polite">
            {activePlan ? `${activePlan.target_user}，${activePlan.time}，${activePlan.medicine}，${activePlan.status}` : "今日暂无用药计划"}
          </span>
          <small className="next-dose-count">{plans.length ? `${planIndex + 1}/${plans.length}` : "0/0"}</small>
        </div>
      </div>
    </section>
  );
}
