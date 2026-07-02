import React from "react";
import { Bot, HeartPulse, Pill } from "lucide-react";
import assistantRobot from "../assets/assistant-robot.svg";
import calendarAsset from "../assets/calendar-3d.svg";
import cameraAsset from "../assets/camera-3d.svg";
import profileAsset from "../assets/profile-folder-3d.svg";
import { api, formBody } from "../api/client.js";
import { BigActionButton } from "../components/BigActionButton.jsx";
import { GlassCard } from "../components/GlassCard.jsx";
import { VitalReadout } from "../components/VitalReadout.jsx";
import { useAsyncAction } from "../hooks/useAsyncAction.js";
import { latestVitals, nextPlan } from "../utils/domain.js";

export function HomePage({ status, site, plans, vitals, medicines, refresh, notify, setPage }) {
  const plan = nextPlan(plans);
  const latest = latestVitals(vitals);
  const qsmOnline = Boolean(status?.qsm?.online);
  const network = status?.network || {};
  const stocked = medicines.filter((item) => Number(item.stock) > 0);
  const emergencyCount = stocked.filter((item) => Number(item.is_emergency) === 1).length;
  const dispenseTitle = plan ? "开始取药" : "暂无计划";
  const dispenseDetail = !plan ? "请在后台添加用药计划" : "dry-run 校验计划与记录";

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
          <h1>今日用药提醒</h1>
          <span className="dose-state">按时</span>
        </div>
        <div className="next-dose">
          <span>下一次服药时间</span>
          <strong>{plan?.time || "--:--"}</strong>
        </div>
        <div className="medicine-summary">
          <div className="medicine-icon">
            <Pill size={66} />
          </div>
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
          disabled={!plan}
          busy={dispensing}
        />
      </GlassCard>

      <GlassCard className="ai-card">
        <div className="ai-copy">
          <span className="card-eyebrow">{site?.station_name || "偏远社区康护站"}</span>
          <h2>开始 AI 应急问询</h2>
          <p>面向村镇弱网场景，结合症状、体征、库存和禁忌做风险提示与药品辅助匹配。</p>
        </div>
        <div className="assistant-stage" aria-hidden="true">
          <img src={assistantRobot} alt="" />
        </div>
        <BigActionButton icon={Bot} title="开始应急问询" detail="低风险才可进入取药确认" tone="purple" onClick={() => setPage("ai")} />
      </GlassCard>

      <GlassCard className="vitals-card">
        <div>
          <h1>站点状态</h1>
          <div className="measure-time">
            <span>{site?.location_name || "村镇智慧用药服务点"}</span>
            <strong>{modeLabel(network.mode || site?.network_mode)}</strong>
          </div>
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

      <button className="home-tile touch-ripple scan" onClick={() => setPage("scan")}>
        <div>
          <strong>扫码/拍照识别</strong>
          <span>药盒、站点码、取药复核</span>
        </div>
        <img src={cameraAsset} alt="" />
      </button>
      <button className="home-tile touch-ripple plan" onClick={() => setPage("cabinet")}>
        <div>
          <strong>可用药品</strong>
          <span>{stocked.length}/23 仓有库存 · 应急 {emergencyCount}</span>
        </div>
        <img src={calendarAsset} alt="" />
      </button>
      <button className="home-tile touch-ripple archive" onClick={() => setPage("profile")}>
        <div>
          <strong>管理员复核</strong>
          <span>{network.pending_sync_count || 0} 条待同步 · {network.sync_status || "本地记录"}</span>
        </div>
        <img src={profileAsset} alt="" />
      </button>
    </div>
  );
}

function modeLabel(mode) {
  return { online: "在线模式", weak: "弱网模式", offline: "离线模式" }[mode] || "弱网模式";
}
