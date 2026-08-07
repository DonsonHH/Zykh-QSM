import React from "react";
import { InquiryEntryCard } from "./InquiryEntryCard.jsx";
import { MedicationSummaryCard } from "./MedicationSummaryCard.jsx";
import { QuickActions } from "./QuickActions.jsx";

export function HomeHero({ dashboard, onNavigate, quickActions, onQuickAction, onQuickDispense, quickDispenseBusyId }) {
  const vitalsAction = quickActions.find((action) => action.id === "vitals") || {
    id: "vitals",
    title: "身体状态测量",
    tone: "blue"
  };

  return (
    <section className="hero-grid" aria-label="首页核心任务">
      <InquiryEntryCard inquiry={dashboard?.inquiry || {}} onStart={() => onNavigate("inquiry")} />
      <div className="home-side-stack">
        <MedicationSummaryCard
          medication={dashboard?.medication || {}}
          onQuickDispense={onQuickDispense}
          quickDispenseBusyId={quickDispenseBusyId}
        />
        <QuickActions actions={[vitalsAction]} onSelect={onQuickAction} />
      </div>
    </section>
  );
}
