import React, { useEffect, useState } from "react";
import { BottomNav } from "./components/BottomNav.jsx";
import { TopBar } from "./components/TopBar.jsx";
import { loadDashboard } from "./api/dashboard.js";
import { mockDashboard } from "./api/mockData.js";
import { Home } from "./pages/Home.jsx";
import { ComingSoon } from "./pages/ComingSoon.jsx";

export function App() {
  const [page, setPage] = useState("home");
  const [dashboard, setDashboard] = useState(mockDashboard);
  const [now, setNow] = useState(new Date());
  const [toast, setToast] = useState("");

  useEffect(() => {
    loadDashboard().then(setDashboard);
    const clock = window.setInterval(() => setNow(new Date()), 1000);
    const refresh = window.setInterval(() => loadDashboard().then(setDashboard), 30000);
    return () => {
      window.clearInterval(clock);
      window.clearInterval(refresh);
    };
  }, []);

  function notify(message) {
    setToast(message);
    window.clearTimeout(notify.timer);
    notify.timer = window.setTimeout(() => setToast(""), 2800);
  }

  function handleNav(nextPage) {
    if (nextPage !== "home") {
      notify("下一阶段开发中");
    }
    setPage(nextPage);
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <section className="kiosk-frame" aria-label="智药康护终端">
        <TopBar site={dashboard.site} chips={dashboard.chips} now={now} />
        {page === "home" ? (
          <Home dashboard={dashboard} onNavigate={handleNav} notify={notify} />
        ) : (
          <ComingSoon page={page} />
        )}
        <BottomNav page={page} onChange={handleNav} />
        <div className={`toast ${toast ? "show" : ""}`} aria-live="polite">
          {toast}
        </div>
      </section>
    </div>
  );
}
