import React, { useEffect, useMemo, useState } from "react";
import { ScanLine } from "lucide-react";
import { confirmDispense } from "../api/dispense.js";
import { loadMedicines } from "../api/medicines.js";
import { CabinetSlotMap } from "../components/CabinetSlotMap.jsx";
import { DispenseConfirmModal } from "../components/DispenseConfirmModal.jsx";
import { MedicineCard } from "../components/MedicineCard.jsx";
import { MedicineDetailPanel } from "../components/MedicineDetailPanel.jsx";

export function Medicines({ notify, focus, onNavigate }) {
  const initialParams = new URLSearchParams(window.location.search);
  const initialMedicineView = initialParams.get("medicineView") === "cabinet" ? "cabinet" : "list";
  const initialMedicineId = initialParams.get("medicineId");
  const [medicines, setMedicines] = useState([]);
  const [selectedMedicine, setSelectedMedicine] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [modalResult, setModalResult] = useState("");
  const [modalError, setModalError] = useState("");
  const [viewMode, setViewMode] = useState(initialMedicineView);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    setLoading(true);
    setLoadError("");
    loadMedicines()
      .then((data) => {
        const loadedMedicines = data.medicines || [];
        setMedicines(loadedMedicines);
        setSelectedMedicine(
          loadedMedicines.find((medicine) => medicine.id === initialMedicineId) || loadedMedicines[0] || null
        );
      })
      .catch((error) => {
        const message = error.message || "药品列表加载失败";
        setLoadError(message);
        notify(message);
      })
      .finally(() => setLoading(false));
  }, [notify]);

  useEffect(() => {
    if (!focus || medicines.length === 0) {
      return;
    }
    const focusedMedicine = focus.medicineId
      ? medicines.find((medicine) => medicine.id === focus.medicineId)
      : null;
    const categoryMedicine = focus.category
      ? medicines.find((medicine) => medicine.category === focus.category)
      : null;
    setViewMode("list");
    setSelectedMedicine(focusedMedicine || categoryMedicine || medicines[0] || null);
  }, [focus, medicines]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("dispenseModal") === "1" && selectedMedicine) {
      setModalOpen(true);
    }
  }, [selectedMedicine]);

  const stockedCount = useMemo(() => medicines.filter((medicine) => medicine.stock > 0).length, [medicines]);

  function openConfirm() {
    if (!selectedMedicine) {
      notify("请先选择药品");
      return;
    }
    setModalResult("");
    setModalError("");
    setModalOpen(true);
  }

  function handleConfirm(payload) {
    setSubmitting(true);
    setModalError("");
    return confirmDispense(payload)
      .then((data) => {
        setModalResult(data.message);
        notify(data.message);
        return data;
      })
      .catch((error) => {
        setModalError(error.message || "取药确认失败");
        throw error;
      })
      .finally(() => setSubmitting(false));
  }

  return (
    <main className="medicines-page" id="main-content">
      <section className={`medicines-main-panel ${viewMode === "cabinet" ? "cabinet-mode" : ""}`}>
        <div className="medicines-heading">
          <h2>家用药品</h2>
          <div className="medicines-heading-actions">
            <span className="medicines-stock-summary">{loading ? "读取中" : `${stockedCount}/23 仓`}</span>
            <div className="medicine-view-toggle" aria-label="药品显示方式">
              <button
                type="button"
                className={viewMode === "list" ? "active" : ""}
                onClick={() => setViewMode("list")}
              >
                名称
              </button>
              <button
                type="button"
                className={viewMode === "cabinet" ? "active" : ""}
                onClick={() => setViewMode("cabinet")}
              >
                编号
              </button>
            </div>
            <button
              className="scan-button"
              type="button"
              onClick={() => (onNavigate ? onNavigate("scan") : notify("扫码识别入口暂不可用"))}
            >
              <ScanLine size={24} aria-hidden="true" />
              <span>扫码识别</span>
            </button>
          </div>
        </div>

        {loading ? (
          <div className="medicine-loading-state" role="status">
            <ScanLine size={36} aria-hidden="true" />
            <strong>正在读取家用药品</strong>
            <small>请稍候</small>
          </div>
        ) : loadError ? (
          <div className="medicine-loading-state error" role="alert">
            <strong>药柜数据读取失败</strong>
            <small>{loadError}</small>
          </div>
        ) : viewMode === "list" ? (
          <div className="medicine-grid" aria-label="药品列表">
            {medicines.map((medicine) => (
              <MedicineCard
                key={medicine.id}
                medicine={medicine}
                selected={selectedMedicine?.id === medicine.id}
                onSelect={setSelectedMedicine}
              />
            ))}
          </div>
        ) : (
          <CabinetSlotMap
            medicines={medicines}
            selectedMedicine={selectedMedicine}
            onSelect={setSelectedMedicine}
            notify={notify}
          />
        )}

      </section>

      <MedicineDetailPanel medicine={selectedMedicine} onConfirm={openConfirm} />

      <DispenseConfirmModal
        medicine={selectedMedicine}
        open={modalOpen}
        submitting={submitting}
        result={modalResult}
        error={modalError}
        onCancel={() => setModalOpen(false)}
        onSubmit={handleConfirm}
      />
    </main>
  );
}
