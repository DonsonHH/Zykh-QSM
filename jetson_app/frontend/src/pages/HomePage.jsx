import React from "react";
import { Bot, CalendarClock, Camera, ClipboardList, HeartPulse, Pill, UserRound } from "lucide-react";
import { api, formBody } from "../api/client.js";
import { BigActionButton } from "../components/BigActionButton.jsx";
import { GlassCard } from "../components/GlassCard.jsx";
import { VitalReadout } from "../components/VitalReadout.jsx";
import { latestVitals, nextPlan } from "../utils/domain.js";

export function HomePage({ status, medicines, plans, records, vitals, refresh, notify, setPage }) {
  const plan = nextPlan(plans);
  const latest = latestVitals(vitals);
  const filledSlots = medicines.filter((item) => Number(item.stock) > 0).length;
  const lowStock = medicines.filter((item) => Number(item.stock) > 0 && Number(item.stock) <= 12).length;
  const qsmOnline = Boolean(status?.qsm?.online);
  const dispenseTitle = plan ? "开始取药" : "暂无计划";
  const dispenseDetail = !plan ? "请先添加用药计划" : !qsmOnline ? "QSM 离线不可开仓" : "校验计划后开仓";

  const dispense = async () => {
    if (!plan) return notify("当前没有可执行用药计划");
    try {
      const data = await api("/api/dispense", formBody({ slot: plan.slot }));
      notify(data.detail || "取药完成");
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  };

  const readVitals = async () => {
    try {
      const data = await api("/api/vitals/read_all", { method: "POST" });
      notify(`体征已写入：心率 ${data.vitals?.heart_rate || "--"}，血氧 ${data.vitals?.spo2 || "--"}`);
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  };

  return (
    <div className="home-page">
      <GlassCard className="today-card">
        <span className="card-eyebrow">今日用药</span>
        <div className="next-dose">
          <span>下一次服药时间</span>
          <strong>{plan?.time || "--:--"}</strong>
        </div>
        <div className="medicine-summary">
          <Pill size={34} />
          <div>
            <h2>{plan?.medicine_name || (plan ? `${plan.slot} 号仓药品` : "暂无用药计划")}</h2>
            <p>{plan ? `${plan.amount || "按计划"} · ${plan.slot} 号仓` : "请在药柜页或后台添加计划"}</p>
          </div>
        </div>
        <BigActionButton icon={Pill} title={dispenseTitle} detail={dispenseDetail} tone="orange" onClick={dispense} disabled={!qsmOnline || !plan} />
      </GlassCard>

      <GlassCard className="ai-card">
        <span className="card-eyebrow">AI 健康助手</span>
        <h2>有问题？问问 AI 健康助手</h2>
        <p>基于档案、最近体征、病例记忆和药柜库存给出建议。</p>
        <div className="assistant-orb">
          <Bot size={66} />
        </div>
        <BigActionButton icon={Bot} title="开始问诊" detail="支持文字与语音" tone="purple" onClick={() => setPage("ai")} />
      </GlassCard>

      <GlassCard className="vitals-card">
        <span className="card-eyebrow">体征监测</span>
        <div className="measure-time">
          <span>最近测量时间</span>
          <strong>{latest.created_at ? latest.created_at.slice(11, 16) : "--:--"}</strong>
        </div>
        <VitalReadout vitals={latest} />
        <BigActionButton icon={HeartPulse} title="立即测量" detail={!qsmOnline ? "等待 QSM 连接" : "心率 血氧 体温"} tone="blue" onClick={readVitals} disabled={!qsmOnline} />
      </GlassCard>

      <button className="home-tile scan" onClick={() => setPage("scan")}>
        <div>
          <strong>拍照识药</strong>
          <span>拍照识别药盒信息</span>
        </div>
        <Camera size={54} />
      </button>
      <button className="home-tile plan" onClick={() => setPage("cabinet")}>
        <div>
          <strong>用药计划</strong>
          <span>查看用药计划与提醒</span>
        </div>
        <CalendarClock size={54} />
      </button>
      <button className="home-tile archive" onClick={() => setPage("profile")}>
        <div>
          <strong>健康档案</strong>
          <span>个人健康档案管理</span>
        </div>
        <UserRound size={54} />
      </button>

      <GlassCard className="home-status-strip">
        <Metric label="药柜占用" value={`${filledSlots}/23`} />
        <Metric label="低库存" value={`${lowStock}`} tone={lowStock ? "warn" : "good"} />
        <Metric label="今日记录" value={`${records.length}`} />
        <Metric label="启用计划" value={`${plans.length}`} />
        <div className="strip-note">
          <ClipboardList size={20} />
          <span>{qsmOnline ? "QSM 外设可用，取药和测量已启用" : "QSM 离线，本地档案和药柜仍可查看"}</span>
        </div>
      </GlassCard>
    </div>
  );
}

function Metric({ label, value, tone = "info" }) {
  return (
    <div className={`home-metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
