import React from "react";
import { CalendarClock, ClipboardList, HeartPulse, UserRound } from "lucide-react";
import { GlassCard } from "../components/GlassCard.jsx";
import { VitalReadout } from "../components/VitalReadout.jsx";

export function ProfilePage({ profile, vitals, medicines, plans, records, setPage }) {
  const activeMeds = medicines.filter((item) => Number(item.stock) > 0);
  const enabledPlans = plans.filter((plan) => Number(plan.enabled) !== 0);
  const recentRecords = records.slice(0, 5);

  return (
    <div className="profile-page">
      <GlassCard className="profile-main-card">
        <span className="card-eyebrow">康护档案</span>
        <div className="profile-hero">
          <div className="avatar xl">
            <UserRound size={54} />
          </div>
          <div>
            <h1>{profile.name || "未填写姓名"}</h1>
            <p>{profile.gender || "未填性别"} · {profile.age || "--"} 岁 · {profile.height || "--"}cm · {profile.weight || "--"}kg</p>
          </div>
        </div>
        <div className="profile-notes">
          <article>
            <span>慢病记录</span>
            <strong>{profile.conditions || "暂无记录"}</strong>
          </article>
          <article>
            <span>过敏史</span>
            <strong>{profile.allergies || "暂无记录"}</strong>
          </article>
          <article>
            <span>备注</span>
            <strong>{profile.notes || "暂无备注"}</strong>
          </article>
        </div>
      </GlassCard>

      <GlassCard className="profile-vitals-card">
        <span className="card-eyebrow">最近体征</span>
        <VitalReadout vitals={vitals[0] || {}} />
        <button onClick={() => setPage("home")}>
          <HeartPulse size={20} />
          返回首页测量
        </button>
      </GlassCard>

      <GlassCard className="profile-plan-card">
        <span className="card-eyebrow">用药计划</span>
        <h2>{enabledPlans.length} 个启用计划</h2>
        <div className="simple-list">
          {enabledPlans.slice(0, 5).map((plan) => (
            <p key={plan.id || `${plan.slot}-${plan.time}`}>
              <CalendarClock size={16} />
              <span>{plan.time} · {plan.medicine_name || `${plan.slot} 号仓`} · {plan.amount}</span>
            </p>
          ))}
          {!enabledPlans.length && <p className="muted">暂无启用计划</p>}
        </div>
      </GlassCard>

      <GlassCard className="profile-record-card">
        <span className="card-eyebrow">最近记录</span>
        <h2>{activeMeds.length}/23 仓有库存</h2>
        <div className="simple-list">
          {recentRecords.map((record) => (
            <p key={record.id}>
              <ClipboardList size={16} />
              <span>{record.created_at} · {record.action} · {record.result}</span>
            </p>
          ))}
          {!recentRecords.length && <p className="muted">暂无操作记录</p>}
        </div>
      </GlassCard>
    </div>
  );
}
