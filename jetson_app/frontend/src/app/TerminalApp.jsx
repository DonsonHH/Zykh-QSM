import React, { useEffect, useMemo, useState } from "react";
import { Activity, ChevronDown, Cpu, HeartHandshake, RadioTower, ShieldCheck, Wifi } from "lucide-react";
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
  cabinet: "可用药品",
  scan: "扫码识别",
  ai: "AI 应急问询",
  profile: "康护档案"
};

const terminalPages = new Set(Object.keys(pageTitles));

export function TerminalApp() {
  const data = useQsmData();
  const scale = useKioskScale();
  const [page, setPage] = useState(() => {
    if (window.location.pathname.startsWith("/triage")) return "ai";
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
        <TerminalTopbar now={now} status={data.status} site={data.site} profile={data.profile} page={page} />
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

function TerminalTopbar({ now, status, site, profile, page }) {
  const qsmOnline = Boolean(status?.qsm?.online);
  const forwardOk = Boolean(status?.qsm?.forward?.ok ?? status?.qsm?.forward);
  const mainOk = Boolean(status?.qsm_main);
  const network = status?.network || {};
  return (
    <header className="terminal-topbar">
      <div className="brand-lockup">
        <div className="brand-icon">
          <HeartHandshake size={30} />
        </div>
        <div>
          <strong>智药康护终端</strong>
          <span>{site?.station_name || "偏远社区康护站"} · {pageTitles[page]}</span>
        </div>
      </div>
      <div className="time-lockup">
        <strong>{formatClock(now)}</strong>
        <span>{formatDay(now)}</span>
      </div>
      <div className="topbar-status">
        <StatusPill icon={RadioTower} label="网络模式" value={modeLabel(network.mode || site?.network_mode)} tone={network.mode === "offline" ? "soft" : network.mode === "online" ? "good" : "warn"} />
        <StatusPill icon={Wifi} label="AI 模式" value={aiModeLabel(network.ai_mode || site?.ai_mode)} tone={(network.ai_mode || site?.ai_mode) === "cloud" ? "good" : "warn"} />
        <StatusPill icon={Cpu} label="外设平台" value={qsmOnline && forwardOk ? "可用" : "部分暂不可用"} tone={qsmOnline && forwardOk ? "good" : "soft"} />
        <StatusPill icon={ShieldCheck} label="同步状态" value={network.pending_sync_count ? `${network.pending_sync_count} 待同步` : (network.sync_status || "已同步")} tone={network.pending_sync_count ? "warn" : mainOk ? "good" : "soft"} />
      </div>
      <a className="admin-peek" href="/admin" aria-label="进入管理后台">
        <Activity size={18} />
        <span>{profile?.name || "管理员"}</span>
        <ChevronDown size={16} />
      </a>
    </header>
  );
}

function modeLabel(mode) {
  return { online: "在线", weak: "弱网", offline: "离线" }[mode] || "弱网";
}

function aiModeLabel(mode) {
  return { cloud: "云端AI", local: "本地AI", rules: "规则兜底" }[mode] || "本地AI";
}

function Toast({ message }) {
  return <div className={`toast ${message ? "show" : ""}`}>{message}</div>;
}
