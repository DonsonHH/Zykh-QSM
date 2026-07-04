import React, { useEffect, useState } from "react";
import { HomeHero } from "../components/HomeHero.jsx";
import { QuickActions } from "../components/QuickActions.jsx";
import { HomeStatusStrip } from "../components/HomeStatusStrip.jsx";

export function Home({ dashboard, onNavigate, notify }) {
  const [stats, setStats] = useState(dashboard?.stats || []);

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

  function handleOpenVitals() {
    onNavigate("vitals", { returnTo: "home" });
  }

  return (
    <main className="home-page" id="main-content">
      <HomeHero dashboard={dashboard} onNavigate={onNavigate} />
      <QuickActions actions={dashboard?.quick_actions || []} onSelect={handleQuickAction} />
      <HomeStatusStrip stats={stats} onOpenVitals={handleOpenVitals} />
    </main>
  );
}
