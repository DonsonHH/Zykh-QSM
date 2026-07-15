import React from "react";
import { InquiryEntryCard } from "./InquiryEntryCard.jsx";
import { MedicationSummaryCard } from "./MedicationSummaryCard.jsx";

export function HomeHero({ dashboard, identity, identityStatus, identityMessage, onNavigate }) {
  return (
    <section className="hero-grid" aria-label="首页核心任务">
      <MedicationSummaryCard
        medication={dashboard?.medication || {}}
        identity={identity}
        identityStatus={identityStatus}
        identityMessage={identityMessage}
      />
      <InquiryEntryCard inquiry={dashboard?.inquiry || {}} onStart={() => onNavigate("inquiry")} />
    </section>
  );
}
