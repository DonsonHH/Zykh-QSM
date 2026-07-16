import React, { useEffect, useMemo } from "react";
import { Fingerprint, ListChecks, UserRound, X } from "lucide-react";
import { medicationPlanTimeLabel, orderMedicationPlans } from "../utils/medicationPlans.js";

export function MedicationTaskPicker({ open, plans, busy, onClose, onPickPlan }) {
  const taskRows = useMemo(
    () => orderMedicationPlans(plans),
    [plans]
  );
  const peopleCount = useMemo(
    () => new Set(plans.map((plan) => plan.target_user).filter(Boolean)).size,
    [plans]
  );

  useEffect(() => {
    if (!open) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, open]);

  if (!open) return null;

  return (
    <div className="modal-layer home-task-picker-layer" onClick={onClose}>
      <section
        className="home-task-picker"
        role="dialog"
        aria-modal="true"
        aria-labelledby="home-task-picker-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="home-task-picker-heading">
          <span className="home-task-picker-icon" aria-hidden="true">
            <ListChecks size={32} strokeWidth={2.2} />
          </span>
          <div>
            <h2 id="home-task-picker-title">选择今日用药任务</h2>
            <p>{peopleCount} 位使用人 · {plans.length} 条待执行</p>
          </div>
          <button type="button" className="home-task-picker-close" onClick={onClose} aria-label="关闭任务列表" title="关闭">
            <X size={26} aria-hidden="true" />
          </button>
        </header>

        <div className="home-task-picker-list" aria-label="今日待执行用药任务">
          {taskRows.map((plan, index) => (
            <button
              key={`${plan.id || "plan"}-${index}`}
              type="button"
              className="home-task-picker-row"
              disabled={busy}
              aria-label={`${medicationPlanTimeLabel(plan)}，${plan.target_user}，${plan.medicine}，${plan.dose || "按说明"}，进入取药`}
              onClick={() => onPickPlan(plan)}
            >
              <strong className="home-task-picker-time">{medicationPlanTimeLabel(plan)}</strong>
              <span className="home-task-picker-person">
                <UserRound size={22} aria-hidden="true" />
                <strong>{plan.target_user || "家庭成员"}</strong>
              </span>
              <span className="home-task-picker-medicine">
                <strong>{plan.medicine}</strong>
                <small>{plan.frequency_label || "每天"} · {plan.dose || "按说明"}</small>
              </span>
              <span className="home-task-picker-action">
                <Fingerprint size={21} aria-hidden="true" />
                取药
              </span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
