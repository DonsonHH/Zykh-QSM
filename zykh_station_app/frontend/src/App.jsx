import React, { useCallback, useEffect, useRef, useState } from "react";
import { BottomNav } from "./components/BottomNav.jsx";
import { TopBar } from "./components/TopBar.jsx";
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
import { Settings } from "./pages/Settings.jsx";
import { IdleScreen } from "./pages/IdleScreen.jsx";
import { useFaceIdentity } from "./hooks/useFaceIdentity.js";

export function App() {
  const initialParams = new URLSearchParams(window.location.search);
  const initialPage = initialParams.get("page") || "home";
  const startsIdle = initialPage === "home" && initialParams.get("awake") !== "1";
  const [page, setPage] = useState(initialPage);
  const [idle, setIdle] = useState(startsIdle);
  const [dashboard, setDashboard] = useState(mockDashboard);
  const [now, setNow] = useState(new Date());
  const [toast, setToast] = useState("");
  const [medicineFocus, setMedicineFocus] = useState(null);
  const [vitalsReturnPage, setVitalsReturnPage] = useState("home");
  const [networkStatus, setNetworkStatus] = useState(null);
  const toastTimerRef = useRef(null);
  const idleTimerRef = useRef(null);
  const { identity, status: identityStatus, message: identityMessage, identify, clear: clearIdentity } =
    useFaceIdentity({ auto: false });
  const configuredIdleSeconds = Number(import.meta.env.VITE_IDLE_TIMEOUT_SECONDS || 90);
  const idleSeconds = Number.isFinite(configuredIdleSeconds) ? Math.max(15, configuredIdleSeconds) : 90;

  useEffect(() => {
    loadNetworkStatus().then(setNetworkStatus).catch(() => setNetworkStatus(null));
    const clock = window.setInterval(() => setNow(new Date()), 1000);
    const networkRefresh = window.setInterval(
      () => loadNetworkStatus().then(setNetworkStatus).catch(() => setNetworkStatus(null)),
      15000
    );
    return () => {
      window.clearInterval(clock);
      window.clearInterval(networkRefresh);
    };
  }, []);

  useEffect(() => {
    const refresh = () => loadDashboard(identity?.name || "__unconfirmed__").then(setDashboard);
    refresh();
    const timer = window.setInterval(refresh, 30000);
    return () => window.clearInterval(timer);
  }, [identity?.name]);

  useEffect(() => {
    if (startsIdle) {
      clearIdentity();
    }
  }, []);

  useEffect(() => {
    if (idle) {
      window.clearTimeout(idleTimerRef.current);
      return undefined;
    }
    const resetTimer = () => {
      window.clearTimeout(idleTimerRef.current);
      idleTimerRef.current = window.setTimeout(() => {
        clearIdentity();
        setMedicineFocus(null);
        setPage("home");
        setIdle(true);
      }, idleSeconds * 1000);
    };
    const events = ["pointerdown", "keydown", "touchstart"];
    events.forEach((event) => window.addEventListener(event, resetTimer, { passive: true }));
    resetTimer();
    return () => {
      window.clearTimeout(idleTimerRef.current);
      events.forEach((event) => window.removeEventListener(event, resetTimer));
    };
  }, [clearIdentity, idle, idleSeconds]);

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
      nextPage !== "vitals" &&
      nextPage !== "settings"
    ) {
      notify("下一阶段开发中");
    }
    if (nextPage === "vitals") {
      setVitalsReturnPage(options.returnTo || page || "home");
    }
    if (nextPage === "medicines" && (options.medicineId || options.category)) {
      setMedicineFocus({ medicineId: options.medicineId || null, category: options.category || null });
    }
    setPage(nextPage);
  }

  function handleViewCandidates(focus) {
    setMedicineFocus(focus);
    setPage("medicines");
    notify("已筛选候选药品，请继续完成用药安全核验");
  }

  function handleWake() {
    clearIdentity();
    setPage("home");
    setIdle(false);
    window.setTimeout(() => {
      identify({ force: true })
        .then((result) => {
          if (!result?.ok) {
            notify(result?.message || "暂时无法确认使用人，请正对摄像头后重试。");
          }
        })
        .catch((error) => notify(error.message || "身份确认暂不可用"));
    }, 250);
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <section className={`kiosk-frame ${idle ? "idle-frame" : ""}`} aria-label="智药康护终端">
        {idle ? (
          <IdleScreen now={now} networkStatus={networkStatus} onWake={handleWake} />
        ) : (
          <>
        <TopBar
          networkStatus={networkStatus}
          now={now}
          page={page}
          onOpenSystemCheck={() => setPage("settings")}
        />
        {page === "home" ? (
          <Home
            dashboard={dashboard}
            identity={identity}
            identityStatus={identityStatus}
            identityMessage={identityMessage}
            onNavigate={handleNav}
            notify={notify}
          />
        ) : page === "medicines" ? (
          <Medicines notify={notify} focus={medicineFocus} onNavigate={handleNav} />
        ) : page === "inquiry" ? (
          <Inquiry
            notify={notify}
            onViewCandidates={handleViewCandidates}
            onNavigate={handleNav}
            networkStatus={networkStatus}
          />
        ) : page === "records" ? (
          <Records notify={notify} networkStatus={networkStatus} />
        ) : page === "scan" ? (
          <Scan notify={notify} onNavigate={handleNav} />
        ) : page === "vitals" ? (
          <Vitals notify={notify} onNavigate={handleNav} returnPage={vitalsReturnPage} />
        ) : page === "settings" ? (
          <Settings
            notify={notify}
            onNavigate={handleNav}
            networkStatus={networkStatus}
            onNetworkStatusChange={setNetworkStatus}
          />
        ) : (
          <ComingSoon page={page} />
        )}
        <BottomNav page={page} onChange={handleNav} />
          </>
        )}
        <div className={`toast ${toast ? "show" : ""}`} aria-live="polite">
          {toast}
        </div>
      </section>
    </div>
  );
}
