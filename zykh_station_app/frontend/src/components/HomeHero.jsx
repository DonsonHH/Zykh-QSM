import React from "react";
import { InquiryEntryCard } from "./InquiryEntryCard.jsx";
import { MedicationSummaryCard } from "./MedicationSummaryCard.jsx";
import { QuickActions } from "./QuickActions.jsx";

export function HomeHero({ dashboard, identity, identityStatus, identityMessage, onNavigate, quickActions, onQuickAction }) {
  const vitalsAction = quickActions.find((action) => action.id === "vitals") || {
    id: "vitals",
    title: "身体状态测量",
    tone: "blue"
  };

  return (
    <section className="hero-grid" aria-label="首页核心任务">
      <MedicationSummaryCard
        medication={dashboard?.medication || {}}
        identity={identity}
        identityStatus={identityStatus}
        identityMessage={identityMessage}
      />
      <div className="home-side-stack">
        <InquiryEntryCard inquiry={dashboard?.inquiry || {}} onStart={() => onNavigate("inquiry")} />
        <QuickActions actions={[vitalsAction]} onSelect={onQuickAction} />
      </div>
    </section>
  );
}
