import React, { useEffect, useMemo } from "react";
import { createPortal } from "react-dom";
import { CheckCircle2, Fingerprint, ListChecks, UserRound, X } from "lucide-react";
import {
  isMedicationPlanCompleted,
  medicationPlanTimeLabel,
  orderMedicationTaskPickerPlans
} from "../utils/medicationPlans.js";
import { useExitPresence } from "../hooks/useExitPresence.js";

export function MedicationTaskPicker({ open, plans, busy, onClose, onPickPlan }) {
  const { present, exiting } = useExitPresence(open);
  const taskRows = useMemo(
    () => orderMedicationTaskPickerPlans(plans),
    [open, plans]
  );
  const completedCount = useMemo(() => plans.filter(isMedicationPlanCompleted).length, [plans]);
  const pendingCount = plans.filter((plan) => plan.status === "待执行").length;
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

  if (!present) return null;

  return createPortal(
    <div className={`modal-layer home-task-picker-layer${exiting ? " is-exiting" : ""}`} onClick={open ? onClose : undefined}>
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
            <p>{peopleCount} 位使用人 · {pendingCount} 条待取{completedCount ? ` · ${completedCount} 条已取` : ""}</p>
          </div>
          <button type="button" className="home-task-picker-close" onClick={onClose} aria-label="关闭任务列表" title="关闭">
            <X size={26} aria-hidden="true" />
          </button>
        </header>

        <div className="home-task-picker-list" aria-label="今日待执行用药任务">
          {taskRows.map((plan, index) => {
            const completed = isMedicationPlanCompleted(plan);
            const unavailable = completed || plan.status === "已跳过";
            const actionLabel = completed ? "已取出" : plan.status === "已跳过" ? "已跳过" : "取药";
            return (
              <button
                key={`${plan.id || "plan"}-${index}`}
                type="button"
                className={`home-task-picker-row${completed ? " completed" : ""}`}
                disabled={busy || unavailable}
                aria-label={`${medicationPlanTimeLabel(plan)}，${plan.target_user}，${plan.medicine}，${plan.dose || "按说明"}，${actionLabel}`}
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
                  {completed ? <CheckCircle2 size={21} aria-hidden="true" /> : <Fingerprint size={21} aria-hidden="true" />}
                  {actionLabel}
                </span>
              </button>
            );
          })}
        </div>
      </section>
    </div>,
    document.querySelector(".kiosk-frame") || document.body
  );
}
