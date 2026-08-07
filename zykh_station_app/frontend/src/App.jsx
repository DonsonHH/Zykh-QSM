import React, { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
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
import { TouchKeyboard } from "./components/TouchKeyboard.jsx";
import { useFaceIdentity } from "./hooks/useFaceIdentity.js";
import { clearInquirySession } from "./utils/inquirySession.js";

const primaryPageOrder = ["home", "medicines", "inquiry", "records"];
const PAGE_ENTRY_CUE_WINDOW_MS = 360;
const MemoHome = memo(Home);
const MemoMedicines = memo(Medicines);
const MemoInquiry = memo(Inquiry);
const MemoRecords = memo(Records);
const MemoScan = memo(Scan);
const MemoVitals = memo(Vitals);
const MemoSettings = memo(Settings);

function sameSnapshot(current, next) {
  if (Object.is(current, next)) return true;
  return JSON.stringify(current) === JSON.stringify(next);
}

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
  const touchKeyboardEnabled = initialParams.get("touchKeyboard") !== "0";
  const startsIdle = initialPage === "home" && initialParams.get("awake") !== "1";
  const [page, setPage] = useState(initialPage);
  const [idle, setIdle] = useState(startsIdle);
  const [dashboard, setDashboard] = useState(mockDashboard);
  const [toast, setToast] = useState("");
  const [medicineFocus, setMedicineFocus] = useState(null);
  const [medicinesMounted, setMedicinesMounted] = useState(initialPage === "medicines");
  const [settingsMounted, setSettingsMounted] = useState(initialPage === "settings");
  const [basicSettingsSnapshot, setBasicSettingsSnapshot] = useState(null);
  const [vitalsReturnPage, setVitalsReturnPage] = useState("home");
  const [networkStatus, setNetworkStatus] = useState(null);
  const configuredIdleSeconds = Number(import.meta.env.VITE_IDLE_TIMEOUT_SECONDS || 90);
  const [idleSeconds, setIdleSeconds] = useState(Number.isFinite(configuredIdleSeconds) ? Math.max(0, configuredIdleSeconds) : 90);
  const toastTimerRef = useRef(null);
  const idleTimerRef = useRef(null);
  const pageRef = useRef(initialPage);
  const visibleHomeDashboardRef = useRef(dashboard);
  const pageTransitionRef = useRef({ kind: "", token: 0 });
  const pageTransitionTimerRef = useRef(null);
  const { clear: clearIdentity } = useFaceIdentity({ auto: false });

  const updateNetworkStatus = useCallback((nextStatus) => {
    setNetworkStatus((currentStatus) => sameSnapshot(currentStatus, nextStatus) ? currentStatus : nextStatus);
  }, []);

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
      }, PAGE_ENTRY_CUE_WINDOW_MS);
    });
  }, [idle, page]);

  useEffect(() => () => {
    window.clearTimeout(pageTransitionTimerRef.current);
    delete document.documentElement.dataset.pageTransition;
  }, []);

  useEffect(() => {
    const applySettings = (settings) => {
      setBasicSettingsSnapshot((current) => sameSnapshot(current, settings) ? current : settings);
      const value = Number(settings?.idle_timeout_seconds);
      if (Number.isFinite(value)) setIdleSeconds(Math.max(0, value));
    };
    loadBasicSettings().then((data) => applySettings(data.settings)).catch(() => undefined);
    const handleSettings = (event) => applySettings(event.detail);
    window.addEventListener("zykh:settings-updated", handleSettings);
    return () => window.removeEventListener("zykh:settings-updated", handleSettings);
  }, []);

  useEffect(() => {
    if (settingsMounted || !basicSettingsSnapshot || idle || page === "admin") return undefined;
    const mountSettings = () => setSettingsMounted(true);
    if (typeof window.requestIdleCallback === "function") {
      const idleCallback = window.requestIdleCallback(mountSettings, { timeout: 1200 });
      return () => window.cancelIdleCallback(idleCallback);
    }
    const timer = window.setTimeout(mountSettings, 300);
    return () => window.clearTimeout(timer);
  }, [basicSettingsSnapshot, idle, page, settingsMounted]);

  useEffect(() => {
    loadNetworkStatus().then(updateNetworkStatus).catch(() => updateNetworkStatus(null));
    const networkRefresh = window.setInterval(
      () => loadNetworkStatus().then(updateNetworkStatus).catch(() => updateNetworkStatus(null)),
      15000
    );
    return () => {
      window.clearInterval(networkRefresh);
    };
  }, [updateNetworkStatus]);

  const refreshDashboard = useCallback(() => loadDashboard().then((nextDashboard) => {
    setDashboard((currentDashboard) => sameSnapshot(currentDashboard, nextDashboard) ? currentDashboard : nextDashboard);
  }), []);

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
    if (idle || page === "admin") {
      setMedicinesMounted(false);
      setSettingsMounted(false);
    }
  }, [idle, page]);

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

  const handleNav = useCallback((nextPage, options = {}) => {
    const currentPage = pageRef.current;
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
        setVitalsReturnPage(options.returnTo || currentPage || "home");
      }
      if (nextPage === "medicines" && (options.medicineId || options.category)) {
        setMedicineFocus({ medicineId: options.medicineId || null, category: options.category || null });
      }
      if (nextPage === "medicines") {
        setMedicinesMounted(true);
      }
      if (nextPage === "settings") {
        setSettingsMounted(true);
      }
      pageRef.current = nextPage;
      setPage(nextPage);
    };
    if (nextPage === currentPage) {
      applyNavigation();
      return;
    }
    commitViewChange(transitionKind(currentPage, nextPage, options.transition), () => {
      applyNavigation();
    });
  }, [commitViewChange, notify]);

  const handleViewCandidates = useCallback((focus) => {
    commitViewChange("forward", () => {
      setMedicineFocus(focus);
      setMedicinesMounted(true);
      pageRef.current = "medicines";
      setPage("medicines");
    });
    notify("已筛选候选药品，请继续完成用药安全核验");
  }, [commitViewChange, notify]);

  const handleWake = useCallback(() => {
    commitViewChange("wake", () => {
      pageRef.current = "home";
      setPage("home");
      setIdle(false);
    });
  }, [commitViewChange]);

  const openSettings = useCallback(() => handleNav("settings"), [handleNav]);
  const exitAdmin = useCallback(
    () => handleNav("settings", { transition: "backward" }),
    [handleNav]
  );

  const visibleHomeDashboard = page === "home" && !idle
    ? dashboard
    : visibleHomeDashboardRef.current;

  useLayoutEffect(() => {
    if (page === "home" && !idle) {
      visibleHomeDashboardRef.current = dashboard;
    }
  }, [dashboard, idle, page]);

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
          <AdminConsole onExit={exitAdmin} />
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
              onOpenSystemCheck={openSettings}
            />
            <div
              className={`page-cache home-page-cache ${page === "home" ? "active" : "inactive"}`}
              id={page === "home" ? "main-content" : undefined}
              aria-hidden={page !== "home"}
              inert={page !== "home" ? "" : undefined}
            >
              <MemoHome
                dashboard={visibleHomeDashboard}
                onNavigate={handleNav}
                notify={notify}
                onDashboardRefresh={refreshDashboard}
              />
            </div>
            {medicinesMounted ? (
              <div
                className={`page-cache medicines-page-cache ${page === "medicines" ? "active" : "inactive"}`}
                id={page === "medicines" ? "main-content" : undefined}
                aria-hidden={page !== "medicines"}
                inert={page !== "medicines" ? "" : undefined}
              >
                <MemoMedicines notify={notify} focus={medicineFocus} onNavigate={handleNav} />
              </div>
            ) : null}
            {settingsMounted ? (
              <div
                className={`page-cache settings-page-cache ${page === "settings" ? "active" : "inactive"}`}
                id={page === "settings" ? "main-content" : undefined}
                aria-hidden={page !== "settings"}
                inert={page !== "settings" ? "" : undefined}
              >
                <MemoSettings
                  initialSettings={basicSettingsSnapshot}
                  notify={notify}
                  onNavigate={handleNav}
                  onNetworkStatusChange={updateNetworkStatus}
                />
              </div>
            ) : null}
            {page === "home" || page === "medicines" || page === "settings" ? null : page === "inquiry" ? (
              <MemoInquiry
                notify={notify}
                onViewCandidates={handleViewCandidates}
                onNavigate={handleNav}
                networkStatus={networkStatus}
              />
            ) : page === "records" ? (
              <MemoRecords notify={notify} networkStatus={networkStatus} />
            ) : page === "scan" ? (
              <MemoScan notify={notify} onNavigate={handleNav} />
            ) : page === "vitals" ? (
              <MemoVitals notify={notify} onNavigate={handleNav} returnPage={vitalsReturnPage} />
            ) : (
              <ComingSoon page={page} />
            )}
            <BottomNav page={page} onChange={handleNav} />
          </>
        )}
        <div className={`toast ${toast ? "show" : ""}`} aria-live="polite">
          {toast}
        </div>
        <TouchKeyboard enabled={touchKeyboardEnabled} />
      </section>
    </div>
  );
}
