import React from "react";
import { HomeHero } from "../components/HomeHero.jsx";

export function Home({ dashboard, onNavigate, notify }) {
  function handleQuickAction(action) {
    if (action.id === "scan") {
      onNavigate("scan");
      return;
    }
    if (action.id === "medicines") {
      onNavigate("medicines");
      return;
    }
    if (action.id === "vitals") {
      onNavigate("vitals", { returnTo: "home" });
      return;
    }
    if (action.id === "records") {
      onNavigate("records");
      return;
    }
    notify("下一阶段开发中");
  }

  return (
    <main className="home-page" id="main-content">
      <HomeHero
        dashboard={dashboard}
        onNavigate={onNavigate}
        quickActions={dashboard?.quick_actions || []}
        onQuickAction={handleQuickAction}
      />
    </main>
  );
}
