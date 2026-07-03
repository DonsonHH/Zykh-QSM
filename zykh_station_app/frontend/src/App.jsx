import React, { useCallback, useEffect, useRef, useState } from "react";
import { BottomNav } from "./components/BottomNav.jsx";
import { TopBar } from "./components/TopBar.jsx";
import { SystemCheckModal } from "./components/SystemCheckModal.jsx";
import { loadDashboard } from "./api/dashboard.js";
import { mockDashboard } from "./api/mockData.js";
import { Home } from "./pages/Home.jsx";
import { ComingSoon } from "./pages/ComingSoon.jsx";
import { Medicines } from "./pages/Medicines.jsx";
import { Inquiry } from "./pages/Inquiry.jsx";
import { Records } from "./pages/Records.jsx";
import { Scan } from "./pages/Scan.jsx";

export function App() {
  const [page, setPage] = useState("home");
  const [dashboard, setDashboard] = useState(mockDashboard);
  const [now, setNow] = useState(new Date());
  const [toast, setToast] = useState("");
  const [medicineFocus, setMedicineFocus] = useState(null);
  const [systemCheckOpen, setSystemCheckOpen] = useState(false);
  const toastTimerRef = useRef(null);

  useEffect(() => {
    loadDashboard().then(setDashboard);
    const clock = window.setInterval(() => setNow(new Date()), 1000);
    const refresh = window.setInterval(() => loadDashboard().then(setDashboard), 30000);
    return () => {
      window.clearInterval(clock);
      window.clearInterval(refresh);
    };
  }, []);

  const notify = useCallback((message) => {
    setToast(message);
    window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(""), 2800);
  }, []);

  function handleNav(nextPage) {
    if (
      nextPage !== "home" &&
      nextPage !== "medicines" &&
      nextPage !== "inquiry" &&
      nextPage !== "records" &&
      nextPage !== "scan"
    ) {
      notify("下一阶段开发中");
    }
    setPage(nextPage);
  }

  function handleViewCandidates(focus) {
    setMedicineFocus(focus);
    setPage("medicines");
    notify("已筛选候选药品，请继续完成用药安全核验");
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <section className="kiosk-frame" aria-label="智药康护终端">
        <TopBar
          site={dashboard.site}
          chips={dashboard.chips}
          now={now}
          onOpenSystemCheck={() => setSystemCheckOpen(true)}
        />
        {page === "home" ? (
          <Home dashboard={dashboard} onNavigate={handleNav} notify={notify} />
        ) : page === "medicines" ? (
          <Medicines notify={notify} focus={medicineFocus} onNavigate={handleNav} />
        ) : page === "inquiry" ? (
          <Inquiry notify={notify} onViewCandidates={handleViewCandidates} />
        ) : page === "records" ? (
          <Records notify={notify} />
        ) : page === "scan" ? (
          <Scan notify={notify} onNavigate={handleNav} />
        ) : (
          <ComingSoon page={page} />
        )}
        <BottomNav page={page} onChange={handleNav} />
        <SystemCheckModal
          open={systemCheckOpen}
          syncLabel={dashboard?.chips?.find((chip) => chip.id === "sync")?.value || "本地记录"}
          notify={notify}
          onClose={() => setSystemCheckOpen(false)}
        />
        <div className={`toast ${toast ? "show" : ""}`} aria-live="polite">
          {toast}
        </div>
      </section>
    </div>
  );
}
