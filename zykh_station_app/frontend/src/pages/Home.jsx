import React, { useEffect, useState } from "react";
import { loadQsmVitals } from "../api/qsm.js";
import { HomeHero } from "../components/HomeHero.jsx";
import { QuickActions } from "../components/QuickActions.jsx";
import { HomeStatusStrip } from "../components/HomeStatusStrip.jsx";

export function Home({ dashboard, onNavigate, notify }) {
  const [stats, setStats] = useState(dashboard?.stats || []);
  const [readingVitals, setReadingVitals] = useState(false);

  useEffect(() => {
    setStats(dashboard?.stats || []);
  }, [dashboard?.stats]);

  function handleQuickAction(action) {
    if (action.id === "scan") {
      onNavigate("scan");
      return;
    }
    if (action.id === "medicines") {
      onNavigate("medicines");
      return;
    }
    if (action.id === "records") {
      onNavigate("records");
      return;
    }
    notify("下一阶段开发中");
  }

  function handleReadVitals() {
    if (readingVitals) {
      return;
    }
    setReadingVitals(true);
    loadQsmVitals()
      .then((data) => {
        if (data.status === "unavailable" || data.ok === false) {
          notify("体征设备暂不可用，已保留本地记录");
          return;
        }
        if (typeof data.temperature === "number") {
          setStats((currentStats) =>
            currentStats.map((stat) =>
              stat.id === "temperature" ? { ...stat, value: data.temperature.toFixed(1) } : stat
            )
          );
        }
        if (data.heart_rate == null || data.spo2 == null) {
          notify("体温已更新，心率/血氧暂不可用");
        } else {
          notify("体征读取已更新");
        }
      })
      .catch(() => notify("体征设备暂不可用，已保留本地记录"))
      .finally(() => setReadingVitals(false));
  }

  return (
    <main className="home-page" id="main-content">
      <HomeHero dashboard={dashboard} onNavigate={onNavigate} />
      <QuickActions actions={dashboard?.quick_actions || []} onSelect={handleQuickAction} />
      <HomeStatusStrip stats={stats} readingVitals={readingVitals} onReadVitals={handleReadVitals} />
    </main>
  );
}
