import React from "react";
import { CheckCircle2, Clock3 } from "lucide-react";

export function TodayPlanList({ plans = [] }) {
  return (
    <section className="records-panel today-plan-panel">
      <div className="records-panel-heading">
        <p>今日用药计划</p>
        <h2>计划概览</h2>
      </div>
      <div className="today-plan-list">
        {plans.map((plan) => {
          const done = plan.status === "已执行";
          const Icon = done ? CheckCircle2 : Clock3;
          return (
            <article key={plan.id} className={done ? "done" : ""}>
              <time>{plan.time}</time>
              <div>
                <strong>{plan.medicine}</strong>
                <span>{plan.status}</span>
              </div>
              <Icon size={22} aria-hidden="true" />
            </article>
          );
        })}
        {plans.length === 0 && <p className="empty-list-note">暂无今日计划</p>}
      </div>
    </section>
  );
}
