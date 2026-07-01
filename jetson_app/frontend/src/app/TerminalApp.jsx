import React, { useEffect, useMemo, useState } from "react";
import { Activity, Bot, ChevronDown, Cpu, HeartHandshake, ShieldCheck, Wifi } from "lucide-react";
import { BottomNav } from "../components/BottomNav.jsx";
import { StatusPill } from "../components/StatusPill.jsx";
import { AiChatPage } from "../pages/AiChatPage.jsx";
import { CabinetPage } from "../pages/CabinetPage.jsx";
import { HomePage } from "../pages/HomePage.jsx";
import { ProfilePage } from "../pages/ProfilePage.jsx";
import { ScanPage } from "../pages/ScanPage.jsx";
import { formatClock, formatDay } from "../utils/domain.js";
import { useJetsonData } from "./useJetsonData.js";

const pageTitles = {
  home: "首页",
  cabinet: "药柜管理",
  scan: "拍照识药",
  ai: "AI 健康助手",
  profile: "健康档案"
};

export function TerminalApp() {
  const data = useJetsonData();
  const [page, setPage] = useState("home");
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const common = useMemo(() => ({ ...data, setPage }), [data]);

  return (
    <main className="viewport terminal-viewport">
      <section className="terminal-shell">
        <TerminalTopbar now={now} status={data.status} profile={data.profile} page={page} />
        <section className="terminal-content">
          {page === "home" && <HomePage {...common} />}
          {page === "cabinet" && <CabinetPage {...common} />}
          {page === "scan" && <ScanPage {...common} />}
          {page === "ai" && <AiChatPage {...common} />}
          {page === "profile" && <ProfilePage {...common} />}
        </section>
        <BottomNav page={page} onChange={setPage} />
        <Toast message={data.toast} />
      </section>
    </main>
  );
}

function TerminalTopbar({ now, status, profile, page }) {
  const qsmOnline = Boolean(status?.qsm?.online);
  const forwardOk = Boolean(status?.qsm?.forward?.ok ?? status?.qsm?.forward);
  return (
    <header className="terminal-topbar">
      <div className="brand-lockup">
        <div className="brand-icon">
          <HeartHandshake size={30} />
        </div>
        <div>
          <strong>智药康护终端</strong>
          <span>{pageTitles[page]}</span>
        </div>
      </div>
      <div className="time-lockup">
        <strong>{formatClock(now)}</strong>
        <span>{formatDay(now)}</span>
      </div>
      <div className="topbar-status">
        <StatusPill icon={Cpu} label="QSM状态" value={qsmOnline ? "在线" : "离线"} tone={qsmOnline ? "good" : "bad"} />
        <StatusPill icon={Wifi} label="网关转发" value={forwardOk ? "正常" : "异常"} tone={forwardOk ? "good" : "warn"} />
        <StatusPill icon={ShieldCheck} label="系统状态" value={status?.jetson ? "正常" : "检查中"} tone={status?.jetson ? "good" : "warn"} />
      </div>
      <a className="admin-peek" href="/admin" aria-label="进入管理后台">
        <Activity size={18} />
        <span>{profile?.name || "管理员"}</span>
        <ChevronDown size={16} />
      </a>
    </header>
  );
}

function Toast({ message }) {
  return <div className={`toast ${message ? "show" : ""}`}>{message}</div>;
}
