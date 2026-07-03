import React from "react";
import { HomeHero } from "../components/HomeHero.jsx";
import { QuickActions } from "../components/QuickActions.jsx";
import { HomeStatusStrip } from "../components/HomeStatusStrip.jsx";

export function Home({ dashboard, onNavigate, notify }) {
  function handleQuickAction(action) {
    if (action.id === "medicines") {
      onNavigate("medicines");
      return;
    }
    if (action.id === "records") {
      onNavigate("records");
      return;
    }
    notify("扫码识别将在第二阶段接入取药确认流程");
  }

  return (
    <main className="home-page" id="main-content">
      <HomeHero dashboard={dashboard} onNavigate={onNavigate} />
      <QuickActions actions={dashboard?.quick_actions || []} onSelect={handleQuickAction} />
      <HomeStatusStrip stats={dashboard?.stats || []} />
    </main>
  );
}
