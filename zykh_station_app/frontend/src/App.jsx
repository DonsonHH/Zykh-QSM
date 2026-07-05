import React, { useCallback, useEffect, useRef, useState } from "react";
import { BottomNav } from "./components/BottomNav.jsx";
import { TopBar } from "./components/TopBar.jsx";
import { SystemCheckModal } from "./components/SystemCheckModal.jsx";
import { loadDashboard } from "./api/dashboard.js";
import { loadNetworkStatus } from "./api/network.js";
import { mockDashboard } from "./api/mockData.js";
import { Home } from "./pages/Home.jsx";
import { ComingSoon } from "./pages/ComingSoon.jsx";
import { Medicines } from "./pages/Medicines.jsx";
import { Inquiry } from "./pages/Inquiry.jsx";
import { Records } from "./pages/Records.jsx";
import { Scan } from "./pages/Scan.jsx";
import { Vitals } from "./pages/Vitals.jsx";

export function App() {
  const initialParams = new URLSearchParams(window.location.search);
  const initialPage = initialParams.get("page") || "home";
  const [page, setPage] = useState(initialPage);
  const [dashboard, setDashboard] = useState(mockDashboard);
  const [now, setNow] = useState(new Date());
  const [toast, setToast] = useState("");
  const [medicineFocus, setMedicineFocus] = useState(null);
  const [vitalsReturnPage, setVitalsReturnPage] = useState("home");
  const [systemCheckOpen, setSystemCheckOpen] = useState(initialParams.get("systemCheck") === "1");
  const [networkStatus, setNetworkStatus] = useState(null);
  const toastTimerRef = useRef(null);

  useEffect(() => {
    loadDashboard().then(setDashboard);
    loadNetworkStatus().then(setNetworkStatus).catch(() => setNetworkStatus(null));
    const clock = window.setInterval(() => setNow(new Date()), 1000);
    const refresh = window.setInterval(() => loadDashboard().then(setDashboard), 30000);
    const networkRefresh = window.setInterval(
      () => loadNetworkStatus().then(setNetworkStatus).catch(() => setNetworkStatus(null)),
      15000
    );
    return () => {
      window.clearInterval(clock);
      window.clearInterval(refresh);
      window.clearInterval(networkRefresh);
    };
  }, []);

  const notify = useCallback((message) => {
    setToast(message);
    window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(""), 2800);
  }, []);

  function handleNav(nextPage, options = {}) {
    if (
      nextPage !== "home" &&
      nextPage !== "medicines" &&
      nextPage !== "inquiry" &&
      nextPage !== "records" &&
      nextPage !== "scan" &&
      nextPage !== "vitals"
    ) {
      notify("下一阶段开发中");
    }
    if (nextPage === "vitals") {
      setVitalsReturnPage(options.returnTo || page || "home");
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
          networkStatus={networkStatus}
          now={now}
          page={page}
          onOpenSystemCheck={() => setSystemCheckOpen(true)}
        />
        {page === "home" ? (
          <Home dashboard={dashboard} onNavigate={handleNav} notify={notify} />
        ) : page === "medicines" ? (
          <Medicines notify={notify} focus={medicineFocus} onNavigate={handleNav} />
        ) : page === "inquiry" ? (
          <Inquiry notify={notify} onViewCandidates={handleViewCandidates} onNavigate={handleNav} />
        ) : page === "records" ? (
          <Records notify={notify} />
        ) : page === "scan" ? (
          <Scan notify={notify} onNavigate={handleNav} />
        ) : page === "vitals" ? (
          <Vitals notify={notify} onNavigate={handleNav} returnPage={vitalsReturnPage} />
        ) : (
          <ComingSoon page={page} />
        )}
        <BottomNav page={page} onChange={handleNav} />
        <SystemCheckModal
          open={systemCheckOpen}
          syncLabel={dashboard?.chips?.find((chip) => chip.id === "sync")?.value || "本地记录"}
          networkStatus={networkStatus}
          onNetworkStatusChange={setNetworkStatus}
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
