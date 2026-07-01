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
import { useQsmData } from "./useQsmData.js";
import { useKioskScale } from "./useKioskScale.js";

const pageTitles = {
  home: "首页",
  cabinet: "药柜管理",
  scan: "拍照识药",
  ai: "AI 健康助手",
  profile: "健康档案"
};

const terminalPages = new Set(Object.keys(pageTitles));

export function TerminalApp() {
  const data = useQsmData();
  const scale = useKioskScale();
  const [page, setPage] = useState(() => {
    const requested = new URLSearchParams(window.location.search).get("page");
    return terminalPages.has(requested) ? requested : "home";
  });
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const common = useMemo(() => ({ ...data, setPage }), [data]);

  return (
    <main className="viewport terminal-viewport">
      <section className="terminal-shell kiosk-canvas" style={{ "--kiosk-scale": scale }}>
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
  const mainOk = Boolean(status?.qsm_main);
  return (
    <header className="terminal-topbar">
      <div className="brand-lockup">
        <div className="brand-icon">
          <HeartHandshake size={30} />
        </div>
        <div>
          <strong>智药康护 QSM</strong>
          <span>{pageTitles[page]}</span>
        </div>
      </div>
      <div className="time-lockup">
        <strong>{formatClock(now)}</strong>
        <span>{formatDay(now)}</span>
      </div>
      <div className="topbar-status">
        <StatusPill icon={Cpu} label="设备连接" value={qsmOnline ? "外设在线" : "连接中"} tone={qsmOnline ? "good" : "soft"} />
        <StatusPill icon={Wifi} label="硬件功能" value={qsmOnline && forwardOk ? "可用" : "部分暂不可用"} tone={qsmOnline && forwardOk ? "good" : "soft"} />
        <StatusPill icon={ShieldCheck} label="系统状态" value={mainOk ? "正常" : "检查中"} tone={mainOk ? "good" : "warn"} />
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
