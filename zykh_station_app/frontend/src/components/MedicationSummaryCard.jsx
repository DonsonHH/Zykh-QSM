import React from "react";
import { CalendarClock, ChevronRight, UsersRound } from "lucide-react";

export function MedicationSummaryCard({ medication, onOpenPlan }) {
  return (
    <section className="card task-card medication-summary-card">
      <div className="card-heading">
        <span className="card-icon blue" aria-hidden="true">
          <CalendarClock size={34} strokeWidth={2.1} />
        </span>
        <div>
          <p className="eyebrow">今日任务</p>
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
        <ChevronRight size={28} aria-hidden="true" />
      </div>

      <button className="primary-action" type="button" onClick={onOpenPlan}>
        查看今日计划
      </button>
    </section>
  );
}
