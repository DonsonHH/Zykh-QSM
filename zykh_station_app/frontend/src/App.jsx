import React, { startTransition, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { BottomNav } from "./components/BottomNav.jsx";
import { TopBar } from "./components/TopBar.jsx";
import { loadDashboard } from "./api/dashboard.js";
import { loadNetworkStatus } from "./api/network.js";
import { loadBasicSettings } from "./api/settings.js";
import { setFingerprintStandby, wakeFingerprint } from "./api/fingerprint.js";
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
import { AdminConsole } from "./pages/AdminConsole.jsx";
import { useFaceIdentity } from "./hooks/useFaceIdentity.js";
import { clearInquirySession } from "./utils/inquirySession.js";
import { enableTouchKeyboardForEvent } from "./utils/touchKeyboard.js";

const primaryPageOrder = ["home", "medicines", "inquiry", "records"];

function transitionKind(currentPage, nextPage, requestedKind) {
  if (requestedKind) {
    return requestedKind;
  }
  const currentIndex = primaryPageOrder.indexOf(currentPage);
  const nextIndex = primaryPageOrder.indexOf(nextPage);
  if (currentIndex >= 0 && nextIndex >= 0) {
    return nextIndex < currentIndex ? "backward" : "forward";
  }
  return nextPage === "home" ? "backward" : "forward";
}

export function App() {
  const initialParams = new URLSearchParams(window.location.search);
  const initialPage = initialParams.get("page") || "home";
  const startsIdle = initialPage === "home" && initialParams.get("awake") !== "1";
  const [page, setPage] = useState(initialPage);
  const [idle, setIdle] = useState(startsIdle);
  const [dashboard, setDashboard] = useState(mockDashboard);
  const [toast, setToast] = useState("");
  const [medicineFocus, setMedicineFocus] = useState(null);
  const [vitalsReturnPage, setVitalsReturnPage] = useState("home");
  const [networkStatus, setNetworkStatus] = useState(null);
  const configuredIdleSeconds = Number(import.meta.env.VITE_IDLE_TIMEOUT_SECONDS || 90);
  const [idleSeconds, setIdleSeconds] = useState(Number.isFinite(configuredIdleSeconds) ? Math.max(0, configuredIdleSeconds) : 90);
  const toastTimerRef = useRef(null);
  const idleTimerRef = useRef(null);
  const pageTransitionRef = useRef({ kind: "", token: 0 });
  const pageTransitionTimerRef = useRef(null);
  const { clear: clearIdentity } = useFaceIdentity({ auto: false });

  const commitViewChange = useCallback((kind, update) => {
    window.clearTimeout(pageTransitionTimerRef.current);
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) {
      pageTransitionRef.current.kind = "";
      delete document.documentElement.dataset.pageTransition;
      update();
      return;
    }
    pageTransitionRef.current = {
      kind,
      token: pageTransitionRef.current.token + 1
    };
    update();
  }, []);

  useLayoutEffect(() => {
    const { kind, token } = pageTransitionRef.current;
    if (!kind) return;
    document.documentElement.dataset.pageTransition = kind;
    window.requestAnimationFrame(() => {
      pageTransitionTimerRef.current = window.setTimeout(() => {
        if (pageTransitionRef.current.token === token) {
          pageTransitionRef.current.kind = "";
          delete document.documentElement.dataset.pageTransition;
        }
      }, 180);
    });
  }, [idle, page]);

  useEffect(() => () => {
    window.clearTimeout(pageTransitionTimerRef.current);
    delete document.documentElement.dataset.pageTransition;
  }, []);

  useEffect(() => {
    const showKeyboard = (event) => enableTouchKeyboardForEvent(event);
    document.addEventListener("pointerdown", showKeyboard, true);
    return () => document.removeEventListener("pointerdown", showKeyboard, true);
  }, []);

  useEffect(() => {
    const applySettings = (settings) => {
      const value = Number(settings?.idle_timeout_seconds);
      if (Number.isFinite(value)) setIdleSeconds(Math.max(0, value));
    };
    loadBasicSettings().then((data) => applySettings(data.settings)).catch(() => undefined);
    const handleSettings = (event) => applySettings(event.detail);
    window.addEventListener("zykh:settings-updated", handleSettings);
    return () => window.removeEventListener("zykh:settings-updated", handleSettings);
  }, []);

  useEffect(() => {
    loadNetworkStatus().then(setNetworkStatus).catch(() => setNetworkStatus(null));
    const networkRefresh = window.setInterval(
      () => loadNetworkStatus().then(setNetworkStatus).catch(() => setNetworkStatus(null)),
      15000
    );
    return () => {
      window.clearInterval(networkRefresh);
    };
  }, []);

  const refreshDashboard = useCallback(() => loadDashboard().then(setDashboard), []);

  useEffect(() => {
    refreshDashboard();
    const timer = window.setInterval(refreshDashboard, 30000);
    return () => window.clearInterval(timer);
  }, [refreshDashboard]);

  useEffect(() => {
    const action = idle ? setFingerprintStandby() : wakeFingerprint();
    action.catch(() => undefined);
  }, [idle]);

  useEffect(() => {
    if (startsIdle) {
      clearInquirySession();
      clearIdentity();
    }
  }, []);

  useEffect(() => {
    if (idle || page === "admin" || idleSeconds === 0) {
      window.clearTimeout(idleTimerRef.current);
      return undefined;
    }
    const resetTimer = () => {
      window.clearTimeout(idleTimerRef.current);
      idleTimerRef.current = window.setTimeout(() => {
        commitViewChange("sleep", () => {
          clearInquirySession();
          clearIdentity();
          setMedicineFocus(null);
          setPage("home");
          setIdle(true);
        });
      }, idleSeconds * 1000);
    };
    const events = ["pointerdown", "keydown", "touchstart"];
    events.forEach((event) => window.addEventListener(event, resetTimer, { passive: true }));
    resetTimer();
    return () => {
      window.clearTimeout(idleTimerRef.current);
      events.forEach((event) => window.removeEventListener(event, resetTimer));
    };
  }, [clearIdentity, idle, idleSeconds, page]);

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
      nextPage !== "settings" &&
      nextPage !== "admin"
    ) {
      notify("下一阶段开发中");
    }
    const applyNavigation = () => {
      if (nextPage === "vitals") {
        setVitalsReturnPage(options.returnTo || page || "home");
      }
      if (nextPage === "medicines" && (options.medicineId || options.category)) {
        setMedicineFocus({ medicineId: options.medicineId || null, category: options.category || null });
      }
      setPage(nextPage);
    };
    if (nextPage === page) {
      applyNavigation();
      return;
    }
    commitViewChange(transitionKind(page, nextPage, options.transition), () => {
      startTransition(applyNavigation);
    });
  }

  function handleViewCandidates(focus) {
    commitViewChange("forward", () => {
      startTransition(() => {
        setMedicineFocus(focus);
        setPage("medicines");
      });
    });
    notify("已筛选候选药品，请继续完成用药安全核验");
  }

  function handleWake() {
    commitViewChange("wake", () => {
      startTransition(() => {
        setPage("home");
        setIdle(false);
      });
    });
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <section
        className={`kiosk-frame ${idle ? "idle-frame" : ""} ${page === "admin" ? "admin-frame" : ""}`}
        aria-label="智药康护终端"
      >
        {page === "admin" ? (
          <AdminConsole onExit={() => handleNav("settings", { transition: "backward" })} />
        ) : idle ? (
          <IdleScreen
            networkStatus={networkStatus}
            medication={dashboard?.medication}
            onWake={handleWake}
          />
        ) : (
          <>
            <TopBar
              networkStatus={networkStatus}
              onOpenSystemCheck={() => handleNav("settings")}
            />
            {page === "home" ? (
              <Home
                dashboard={dashboard}
                onNavigate={handleNav}
                notify={notify}
                onDashboardRefresh={refreshDashboard}
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
