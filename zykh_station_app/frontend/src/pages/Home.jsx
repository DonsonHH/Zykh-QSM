import React, { useEffect, useState } from "react";
import { confirmDispense } from "../api/dispense.js";
import { loadMedicine } from "../api/medicines.js";
import { DispenseConfirmModal } from "../components/DispenseConfirmModal.jsx";
import { HomeHero } from "../components/HomeHero.jsx";

export function Home({ dashboard, onNavigate, notify, onDashboardRefresh }) {
  const [quickDispense, setQuickDispense] = useState(null);
  const [loadingMedicine, setLoadingMedicine] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [modalResult, setModalResult] = useState("");
  const [modalError, setModalError] = useState("");

  useEffect(() => {
    const refresh = () => onDashboardRefresh?.();
    window.addEventListener("zykh:medicine-updated", refresh);
    return () => window.removeEventListener("zykh:medicine-updated", refresh);
  }, [onDashboardRefresh]);

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

  function startQuickDispense(plan) {
    if (!plan?.medicine_id || loadingMedicine) return;
    setLoadingMedicine(true);
    setModalError("");
    setModalResult("");
    loadMedicine(plan.medicine_id)
      .then((response) => setQuickDispense({ plan, medicine: response.medicine }))
      .catch((error) => notify(error.message || "用药计划读取失败"))
      .finally(() => setLoadingMedicine(false));
  }

  function submitQuickDispense(payload) {
    setSubmitting(true);
    setModalError("");
    return confirmDispense(payload)
      .then((response) => {
        setModalResult(response.message);
        notify(response.message);
        if (response.ok) {
          if (!response.dry_run) {
            window.dispatchEvent(new CustomEvent("zykh:dispense-recorded", {
              detail: { medicine_id: payload.medicine_id }
            }));
          }
          onDashboardRefresh?.();
        }
        return response;
      })
      .catch((error) => {
        setModalError(error.message || "取药确认失败");
        throw error;
      })
      .finally(() => setSubmitting(false));
  }

  return (
    <main className="home-page">
      <HomeHero
        dashboard={dashboard}
        onNavigate={onNavigate}
        quickActions={dashboard?.quick_actions || []}
        onQuickAction={handleQuickAction}
        onQuickDispense={startQuickDispense}
        quickDispenseBusy={loadingMedicine}
      />
      <DispenseConfirmModal
        medicine={quickDispense?.medicine || null}
        plan={quickDispense?.plan || null}
        open={Boolean(quickDispense)}
        submitting={submitting}
        result={modalResult}
        error={modalError}
        onCancel={() => setQuickDispense(null)}
        onSubmit={submitQuickDispense}
      />
    </main>
  );
}
