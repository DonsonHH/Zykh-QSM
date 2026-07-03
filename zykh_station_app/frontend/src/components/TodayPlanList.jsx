import React from "react";
import { CheckCircle2, Clock3 } from "lucide-react";

const todayPlans = [
  { id: "plan-0800", time: "08:00", medicine: "阿司匹林肠溶片", status: "已执行" },
  { id: "plan-1830", time: "18:30", medicine: "降压片", status: "待执行" },
  { id: "plan-2000", time: "20:00", medicine: "胃药片", status: "待执行" }
];

export function TodayPlanList() {
  return (
    <section className="records-panel today-plan-panel">
      <div className="records-panel-heading">
        <p>今日用药计划</p>
        <h2>计划概览</h2>
      </div>
      <div className="today-plan-list">
        {todayPlans.map((plan) => {
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
      </div>
    </section>
  );
}
