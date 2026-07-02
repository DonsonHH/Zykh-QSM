import React from "react";
import { Bot, CalendarPlus, ChevronRight, ClipboardList, HeartPulse, PackageCheck, ScanLine } from "lucide-react";
import assistantRobot from "../assets/assistant-robot.svg";
import { api } from "../api/client.js";
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
  const stocked = medicines.filter((item) => Number(item.stock) > 0);
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
        <div className="home-card-icon">
          <CalendarPlus size={54} />
        </div>
        <div className="home-card-copy">
          <h1>今日用药</h1>
          <div className="dose-metrics-row">
            <article><span>待服药对象</span><strong>{serviceObjects.length}</strong><small>人</small></article>
            <article><span>待执行</span><strong>{plans.length}</strong><small>条</small></article>
            <article><span>下次时间</span><strong>{plan?.time || "08:00"}</strong></article>
          </div>
        </div>
        <button className="person-row touch-ripple" onClick={() => setPage("profile")}>
          <span className="avatar sm">张</span>
          <strong>张三</strong>
          <em>{plan?.medicine_name || "阿司匹林肠溶片"}</em>
          <ChevronRight size={28} />
        </button>
        <button className="hero-action blue touch-ripple" onClick={() => setPage("profile")}>
          查看今日计划
          <ChevronRight size={30} />
        </button>
      </GlassCard>

      <GlassCard className="ai-card">
        <div className="ai-copy">
          <div className="home-card-icon purple">
            <Bot size={54} />
          </div>
          <h2>AI应急问询</h2>
          <p>智能问答，快速解答<br />用药与健康问题</p>
        </div>
        <div className="assistant-stage home-robot" aria-hidden="true">
          <img src={assistantRobot} alt="" />
        </div>
        <button className="hero-action purple touch-ripple" onClick={() => setPage("ai")}>
          开始问询
          <ChevronRight size={30} />
        </button>
      </GlassCard>

      <button className="home-tile touch-ripple scan" onClick={() => { window.location.href = "/admin?section=scan"; }}>
        <span className="tile-icon"><ScanLine size={44} /></span>
        <div>
          <strong>扫码识别</strong>
          <span>药盒 / 条码 / 站点码</span>
        </div>
        <ChevronRight size={32} />
      </button>
      <button className="home-tile touch-ripple plan" onClick={() => setPage("cabinet")}>
        <span className="tile-icon"><PackageCheck size={44} /></span>
        <div>
          <strong>站点药品</strong>
          <span>{stocked.length}/23 仓有库存</span>
        </div>
        <ChevronRight size={32} />
      </button>
      <button className="home-tile touch-ripple archive" onClick={() => setPage("profile")}>
        <span className="tile-icon"><ClipboardList size={44} /></span>
        <div>
          <strong>服务记录</strong>
          <span>{todayRecords} 条本地记录</span>
        </div>
        <ChevronRight size={32} />
      </button>

      <GlassCard className="home-status-strip">
        <article><PackageCheck size={28} /><span>药柜</span><strong>{stocked.length}<small>/23</small></strong></article>
        <article><HeartPulse size={28} /><span>体温</span><strong>{latest?.temperature || "35.7"}<small>℃</small></strong></article>
        <article><ClipboardList size={28} /><span>设备</span><strong>{qsmOnline ? "可用" : "部分可用"}</strong></article>
      </GlassCard>
    </div>
  );
}

function modeLabel(mode) {
  return { online: "在线模式", weak: "弱网模式", offline: "离线模式" }[mode] || "弱网模式";
}
