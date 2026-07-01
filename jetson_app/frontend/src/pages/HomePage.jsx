import React from "react";
import { Bot, CalendarClock, Camera, HeartPulse, Pill, UserRound } from "lucide-react";
import { api, formBody } from "../api/client.js";
import { BigActionButton } from "../components/BigActionButton.jsx";
import { GlassCard } from "../components/GlassCard.jsx";
import { VitalReadout } from "../components/VitalReadout.jsx";
import { useAsyncAction } from "../hooks/useAsyncAction.js";
import { latestVitals, nextPlan } from "../utils/domain.js";

export function HomePage({ status, plans, vitals, refresh, notify, setPage }) {
  const plan = nextPlan(plans);
  const latest = latestVitals(vitals);
  const qsmOnline = Boolean(status?.qsm?.online);
  const dispenseTitle = plan ? "开始取药" : "暂无计划";
  const dispenseDetail = !plan ? "请先添加用药计划" : !qsmOnline ? "设备连接中，暂不可取药" : "校验计划后开仓";

  const [dispense, dispensing] = useAsyncAction(async () => {
    if (!plan) return notify("当前没有可执行用药计划");
    try {
      const data = await api("/api/dispense", formBody({ slot: plan.slot }));
      notify(data.detail || "取药完成");
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  });

  const [readVitals, readingVitals] = useAsyncAction(async () => {
    try {
      const data = await api("/api/vitals/read_all", { method: "POST" });
      notify(`体征已写入：心率 ${data.vitals?.heart_rate || "--"}，血氧 ${data.vitals?.spo2 || "--"}`);
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  });

  return (
    <div className="home-page">
      <GlassCard className="today-card">
        <div className="card-title-row">
          <span className="card-eyebrow">今日用药</span>
          <span className="dose-state">按时</span>
        </div>
        <div className="next-dose">
          <span>下一次服药时间</span>
          <strong>{plan?.time || "--:--"}</strong>
        </div>
        <div className="medicine-summary">
          <Pill size={34} />
          <div>
            <h2>{plan?.medicine_name || (plan ? `${plan.slot} 号仓药品` : "暂无用药计划")}</h2>
            <p>{plan ? `${plan.amount || "按计划"} · ${plan.slot} 号仓` : "请在药柜页或后台添加计划"}</p>
            {plan && <small>饭后服用</small>}
          </div>
        </div>
        <BigActionButton
          icon={Pill}
          title={dispensing ? "取药中" : dispenseTitle}
          detail={dispensing ? "正在校验计划并开仓" : dispenseDetail}
          tone="orange"
          onClick={dispense}
          disabled={!qsmOnline || !plan}
          busy={dispensing}
        />
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
        <BigActionButton
          icon={HeartPulse}
          title={readingVitals ? "测量中" : "立即测量"}
          detail={readingVitals ? "正在读取心率 血氧 体温" : !qsmOnline ? "设备连接中，暂不可测量" : "心率 血氧 体温"}
          tone="blue"
          onClick={readVitals}
          disabled={!qsmOnline}
          busy={readingVitals}
        />
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
    </div>
  );
}
