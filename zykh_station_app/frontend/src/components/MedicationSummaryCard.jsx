import React, { useEffect, useMemo, useState } from "react";
import { CalendarClock, Fingerprint, ListChecks } from "lucide-react";
import { medicationPlanTimeLabel, selectNearestMedicationPlans } from "../utils/medicationPlans.js";
import { MedicationTaskPicker } from "./MedicationTaskPicker.jsx";

export function MedicationSummaryCard({ medication, onQuickDispense, quickDispenseBusy = false }) {
  const [now, setNow] = useState(new Date());
  const [taskPickerOpen, setTaskPickerOpen] = useState(false);
  const plans = useMemo(() => {
    const availablePlans = medication.plans?.length
      ? medication.plans
      : medication.featured_medicine
        ? [
            {
              id: "featured-plan",
              time: medication.next_time || "--:--",
              medicine: medication.featured_medicine,
              status: "待执行",
              target_user: medication.featured_subject || "家庭成员"
            }
          ]
        : [];
    return availablePlans;
  }, [medication.featured_medicine, medication.featured_subject, medication.next_time, medication.plans]);
  const pendingPlans = useMemo(() => plans.filter((plan) => plan.status === "待执行"), [plans]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  function pickPlanAndDispense(plan) {
    setTaskPickerOpen(false);
    onQuickDispense?.(plan);
  }

  const visiblePlans = useMemo(() => selectNearestMedicationPlans(pendingPlans, now, 3), [now, pendingPlans]);

  return (
    <section className="card task-card medication-summary-card">
      <div className="card-heading compact">
        <span className="card-icon blue" aria-hidden="true">
          <CalendarClock size={30} strokeWidth={2.1} />
        </span>
        <div>
          <h2>今日用药</h2>
        </div>
        {plans.length ? (
          <button type="button" className="home-plan-picker-trigger" onClick={() => setTaskPickerOpen(true)}>
            <ListChecks size={21} aria-hidden="true" />
            全部待办
            <strong>{pendingPlans.length}</strong>
          </button>
        ) : null}
      </div>

      <div className="home-medication-list" aria-label="最近的待执行用药任务">
        {visiblePlans.length ? visiblePlans.map((plan) => (
          <button
            key={plan.id}
            type="button"
            className="home-medication-row"
            disabled={quickDispenseBusy}
            aria-label={`${medicationPlanTimeLabel(plan)}，${plan.target_user}，${plan.medicine}，进入取药`}
            onClick={() => onQuickDispense?.(plan)}
          >
            <strong className="home-medication-time">{medicationPlanTimeLabel(plan)}</strong>
            <span className="home-medication-detail">
              <span><strong>{plan.target_user || "家庭成员"}</strong> · {plan.frequency_label || "每天"} · {plan.dose || "按说明"}</span>
              <strong>{plan.medicine}</strong>
              <small>待取出</small>
            </span>
            <span className="home-medication-action" aria-hidden="true">
              <Fingerprint size={20} />
              取药
            </span>
          </button>
        )) : (
          <div className="home-medication-empty">今日暂无待执行任务</div>
        )}
      </div>

      <MedicationTaskPicker
        open={taskPickerOpen}
        plans={plans}
        busy={quickDispenseBusy}
        onClose={() => setTaskPickerOpen(false)}
        onPickPlan={pickPlanAndDispense}
      />
    </section>
  );
}
