import React, { useEffect, useMemo, useState } from "react";
import { ScanLine } from "lucide-react";
import { confirmDispense } from "../api/dispense.js";
import { loadMedicines } from "../api/medicines.js";
import { CabinetSlotMap } from "../components/CabinetSlotMap.jsx";
import { DispenseConfirmModal } from "../components/DispenseConfirmModal.jsx";
import { MedicineCard } from "../components/MedicineCard.jsx";
import { MedicineDetailPanel } from "../components/MedicineDetailPanel.jsx";

export function Medicines({ notify, focus, onNavigate }) {
  const initialMedicineView =
    new URLSearchParams(window.location.search).get("medicineView") === "cabinet" ? "cabinet" : "list";
  const [medicines, setMedicines] = useState([]);
  const [selectedMedicine, setSelectedMedicine] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [modalResult, setModalResult] = useState("");
  const [modalError, setModalError] = useState("");
  const [viewMode, setViewMode] = useState(initialMedicineView);

  useEffect(() => {
    loadMedicines()
      .then((data) => {
        setMedicines(data.medicines || []);
        setSelectedMedicine((data.medicines || [])[0] || null);
      })
      .catch((error) => notify(error.message || "药品列表加载失败"));
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

  const visibleMedicines = useMemo(() => medicines.filter((medicine) => medicine.stock > 0), [medicines]);

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
    confirmDispense(payload)
      .then((data) => {
        setModalResult(data.message);
        notify(data.message);
      })
      .catch((error) => setModalError(error.message || "取药确认失败"))
      .finally(() => setSubmitting(false));
  }

  return (
    <main className="medicines-page" id="main-content">
      <section className={`medicines-main-panel ${viewMode === "cabinet" ? "cabinet-mode" : ""}`}>
        <div className="medicines-heading">
          <div>
            <h2>家庭药柜</h2>
            <p>{medicines.length}/23 仓有库存</p>
          </div>
          <div className="medicines-heading-actions">
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

        {viewMode === "list" ? (
          <div className="medicine-grid" aria-label="药品列表">
            {visibleMedicines.map((medicine) => (
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

        <p className="medicine-list-note">
          {viewMode === "list"
            ? `当前显示 ${visibleMedicines.length} 种有库存药品。`
            : "点击编号仓门查看对应药品；取药确认仍需完成安全核验。"}
        </p>
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
