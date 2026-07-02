import React from "react";
import { CalendarClock, ClipboardList, HeartPulse, ShieldCheck, UsersRound } from "lucide-react";
import { GlassCard } from "../components/GlassCard.jsx";

const serviceObjects = [
  { name: "张三", meta: "65岁 · 高血压 · 糖尿病前期", status: "今日有用药计划", tone: "good" },
  { name: "李四", meta: "72岁 · 糖尿病随访", status: "待体征复查", tone: "warn" },
  { name: "王五", meta: "58岁 · 长期胃病", status: "近期问询对象", tone: "soft" }
];

export function ProfilePage({ vitals, medicines, plans, records, adminLogs, setPage }) {
  const activeMeds = medicines.filter((item) => Number(item.stock) > 0);
  const enabledPlans = plans.filter((plan) => Number(plan.enabled) !== 0);
  const recentRecords = records.slice(0, 4);
  const emergencySessions = (adminLogs?.emergency_sessions || []).slice(0, 4);
  const dispenseRecords = (adminLogs?.dispense_records || []).slice(0, 4);
  const pendingSync = adminLogs?.pending_sync_count || 0;
  const latestVitals = vitals[0] || {};

  return (
    <div className="records-page">
      <GlassCard className="service-object-card">
        <div className="page-heading compact">
          <div>
            <span className="card-eyebrow">康护服务记录</span>
            <h1>固定服务对象</h1>
          </div>
          <UsersRound size={40} />
        </div>
        <div className="service-object-list">
          {serviceObjects.map((item) => (
            <article key={item.name} className={item.tone}>
              <div className="avatar sm">{item.name.slice(0, 1)}</div>
              <div>
                <strong>{item.name}</strong>
                <span>{item.meta}</span>
              </div>
              <em>{item.status}</em>
            </article>
          ))}
        </div>
        <button className="primary wide" onClick={() => setPage("ai")}>
          <ShieldCheck size={20} />
          发起现场问询
        </button>
      </GlassCard>

      <GlassCard className="service-event-card">
        <div className="page-heading compact">
          <div>
            <span className="card-eyebrow">最近体征与问询</span>
            <h1>风险与复核</h1>
          </div>
          <HeartPulse size={40} />
        </div>
        <div className="vitals-summary-row">
          <article><span>心率</span><strong>{latestVitals.heart_rate || "--"}</strong></article>
          <article><span>血氧</span><strong>{latestVitals.spo2 || "--"}%</strong></article>
          <article><span>体温</span><strong>{latestVitals.temperature || "--"}℃</strong></article>
        </div>
        <div className="service-list">
          {emergencySessions.map((item) => (
            <p key={item.id || item.created_at}>
              <ClipboardList size={16} />
              <span>{item.created_at || item.started_at} · {riskLabel(item.risk_level)} · {item.symptoms_summary || item.symptoms_text}</span>
              <strong>{Number(item.need_admin_review) ? "需复核" : "已记录"}</strong>
            </p>
          ))}
          {!emergencySessions.length && <p className="muted">暂无应急问询记录</p>}
          {recentRecords.map((record) => (
            <p key={record.id}>
              <ClipboardList size={16} />
              <span>{record.created_at} · {record.action} · {record.detail || record.result}</span>
              <strong>本地</strong>
            </p>
          ))}
        </div>
      </GlassCard>

      <GlassCard className="service-plan-card">
        <div className="page-heading compact">
          <div>
            <span className="card-eyebrow">用药计划与出药记录</span>
            <h1>今日队列</h1>
          </div>
          <CalendarClock size={40} />
        </div>
        <div className="records-kpi-grid">
          <article><span>启用计划</span><strong>{enabledPlans.length}</strong></article>
          <article><span>库存仓位</span><strong>{activeMeds.length}/23</strong></article>
          <article><span>待同步</span><strong>{pendingSync}</strong></article>
        </div>
        <div className="service-list">
          {enabledPlans.slice(0, 4).map((plan) => (
            <p key={plan.id || `${plan.slot}-${plan.time}`}>
              <CalendarClock size={16} />
              <span>{plan.time} · 张三 · {plan.medicine_name || `${plan.slot} 号仓`} · {plan.amount}</span>
              <strong>待确认</strong>
            </p>
          ))}
          {dispenseRecords.map((item) => (
            <p key={`dispense-${item.id || item.created_at}`}>
              <ShieldCheck size={16} />
              <span>{item.created_at} · {item.medicine_name || `${item.slot} 号仓`} · {Number(item.dry_run) ? "dry-run" : "已执行"}</span>
              <strong>{Number(item.success) ? "完成" : "异常"}</strong>
            </p>
          ))}
        </div>
      </GlassCard>
    </div>
  );
}

function riskLabel(value) {
  return { low: "低风险", medium: "中风险", high: "高风险", emergency: "紧急风险" }[value] || "待评估";
}
