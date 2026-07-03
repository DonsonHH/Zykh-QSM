import React from "react";
import { Bot, CalendarClock, ChevronRight, ShieldCheck } from "lucide-react";
import { PrimaryCard } from "../components/PrimaryCard.jsx";
import { QuickActionCard } from "../components/QuickActionCard.jsx";
import { StatStrip } from "../components/StatStrip.jsx";

export function Home({ dashboard, onNavigate, notify }) {
  const medication = dashboard?.medication || {};
  const inquiry = dashboard?.inquiry || {};
  const quickActions = dashboard?.quick_actions || [];

  function handleQuickAction(action) {
    if (action.id === "medicines") {
      onNavigate("medicines");
      return;
    }
    if (action.id === "records") {
      onNavigate("records");
      return;
    }
    notify("扫码识别将在第二阶段接入取药确认流程");
  }

  return (
    <main className="home-page" id="main-content">
      <section className="hero-grid">
        <PrimaryCard
          className="medication-card"
          icon={<CalendarClock size={54} strokeWidth={2.1} />}
          title="今日用药"
          actionLabel="查看今日计划"
          onAction={() => onNavigate("records")}
        >
          <div className="dose-row">
            <article>
              <span>待服药对象</span>
              <strong>{medication.pending_people ?? 0}</strong>
              <small>人</small>
            </article>
            <article>
              <span>待执行</span>
              <strong>{medication.pending_plans ?? 0}</strong>
              <small>条</small>
            </article>
            <article>
              <span>下次时间</span>
              <strong>{medication.next_time || "--:--"}</strong>
            </article>
          </div>
          <div className="featured-person">
            <span className="avatar">{(medication.featured_subject || "服").slice(0, 1)}</span>
            <strong>{medication.featured_subject || "固定服务对象"}</strong>
            <em>{medication.featured_medicine || "暂无计划"}</em>
            <ChevronRight size={26} aria-hidden="true" />
          </div>
        </PrimaryCard>

        <PrimaryCard
          className="inquiry-card"
          icon={<Bot size={54} strokeWidth={2.1} />}
          title={inquiry.title || "AI应急问询"}
          actionLabel={inquiry.action_label || "开始问询"}
          onAction={() => onNavigate("inquiry")}
        >
          <p className="inquiry-copy">{inquiry.description}</p>
          <div className="safety-line">
            <ShieldCheck size={22} aria-hidden="true" />
            <span>先核验风险，再进入取药确认。</span>
          </div>
        </PrimaryCard>
      </section>

      <section className="quick-grid" aria-label="快捷入口">
        {quickActions.map((action) => (
          <QuickActionCard key={action.id} action={action} onSelect={handleQuickAction} />
        ))}
      </section>

      <StatStrip stats={dashboard?.stats || []} />
    </main>
  );
}
