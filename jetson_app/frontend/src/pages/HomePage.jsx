import React from "react";
import { Bot, ClipboardList, HeartPulse, Pill, ShieldCheck } from "lucide-react";
import assistantRobot from "../assets/assistant-robot.svg";
import calendarAsset from "../assets/calendar-3d.svg";
import cameraAsset from "../assets/camera-3d.svg";
import profileAsset from "../assets/profile-folder-3d.svg";
import { api } from "../api/client.js";
import { BigActionButton } from "../components/BigActionButton.jsx";
import { GlassCard } from "../components/GlassCard.jsx";
import { useAsyncAction } from "../hooks/useAsyncAction.js";
import { latestVitals, nextPlan } from "../utils/domain.js";

const serviceObjects = [
  { name: "张三", age: 65, tag: "高血压 · 饭后服药", next: "08:00 阿司匹林肠溶片" },
  { name: "李四", age: 72, tag: "糖尿病随访", next: "今日体征复查" },
  { name: "王五", age: 58, tag: "长期胃病", next: "近期问询对象" }
];

export function HomePage({ status, site, plans, vitals, medicines, records, adminLogs, refresh, notify, setPage }) {
  const plan = nextPlan(plans);
  const latest = latestVitals(vitals);
  const qsmOnline = Boolean(status?.qsm?.online);
  const network = status?.network || {};
  const devices = status?.devices || {};
  const stocked = medicines.filter((item) => Number(item.stock) > 0);
  const emergencyCount = stocked.filter((item) => Number(item.is_emergency) === 1).length;
  const pendingReview = (adminLogs?.emergency_sessions || []).filter((item) => Number(item.need_admin_review) === 1).length;
  const pendingSync = Number(network.pending_sync_count || adminLogs?.pending_sync_count || 0);
  const todayRecords = records?.length || 0;

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
          <h1>固定对象今日用药</h1>
          <span className="dose-state">{serviceObjects.length} 人</span>
        </div>
        <div className="station-metrics primary">
          <article>
            <span>待服药对象</span>
            <strong>{serviceObjects.length}人</strong>
          </article>
          <article>
            <span>待执行计划</span>
            <strong>{plans.length}条</strong>
          </article>
        </div>
        <div className="medicine-summary">
          <div className="medicine-icon">
            <Pill size={66} />
          </div>
          <div>
            <h2>下一条：{plan?.time || "08:00"} 张三</h2>
            <p>{plan?.medicine_name || "阿司匹林肠溶片"} · {plan?.amount || "1片"} · 饭后服用</p>
            <small>张三只是固定服务对象之一，站点同时服务多名对象。</small>
          </div>
        </div>
        <BigActionButton
          icon={ClipboardList}
          title="查看今日计划"
          detail={`${todayRecords} 条服务记录 · 执行取药确认需完成核验`}
          tone="orange"
          onClick={() => setPage("profile")}
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
        <div className="station-status-grid">
          <article>
            <span>药柜库存</span>
            <strong>{stocked.length}/23</strong>
          </article>
          <article>
            <span>待复核</span>
            <strong>{pendingReview}</strong>
          </article>
          <article>
            <span>待同步</span>
            <strong>{pendingSync}</strong>
          </article>
          <article>
            <span>外设接入</span>
            <strong>{qsmOnline ? "可用" : "部分不可用"}</strong>
          </article>
        </div>
        <div className="device-strip">
          <span>摄像头 {deviceLabel(devices.camera?.ok)}</span>
          <span>体征 {deviceLabel(devices.vitals?.ok)}</span>
          <span>语音 {deviceLabel(devices.voice?.ok)}</span>
          <span>出药 {devices.dispense?.dry_run ? "演示模式" : deviceLabel(devices.dispense?.ok)}</span>
        </div>
        <BigActionButton
          icon={ShieldCheck}
          title="查看复核队列"
          detail={`最近体征：心率 ${latest?.heart_rate || "--"} · 血氧 ${latest?.spo2 || "--"}`}
          tone="blue"
          onClick={() => setPage("profile")}
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
      <button className="home-tile touch-ripple vitals" onClick={readVitals} disabled={!qsmOnline || readingVitals}>
        <div>
          <strong>{readingVitals ? "测量中" : "体征测量"}</strong>
          <span>{qsmOnline ? "心率、血氧、体温" : "外设接入中"}</span>
        </div>
        <HeartPulse size={58} />
      </button>
    </div>
  );
}

function modeLabel(mode) {
  return { online: "在线模式", weak: "弱网模式", offline: "离线模式" }[mode] || "弱网模式";
}

function deviceLabel(ok) {
  return ok ? "可用" : "待连接";
}
