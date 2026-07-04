import React, { useEffect, useMemo, useState } from "react";
import { ScanLine } from "lucide-react";
import { confirmDispense } from "../api/dispense.js";
import { loadMedicines } from "../api/medicines.js";
import { CabinetSlotMap } from "../components/CabinetSlotMap.jsx";
import { CategoryTabs } from "../components/CategoryTabs.jsx";
import { DispenseConfirmModal } from "../components/DispenseConfirmModal.jsx";
import { MedicineCard } from "../components/MedicineCard.jsx";
import { MedicineDetailPanel } from "../components/MedicineDetailPanel.jsx";

export function Medicines({ notify, focus, onNavigate }) {
  const initialMedicineView =
    new URLSearchParams(window.location.search).get("medicineView") === "cabinet" ? "cabinet" : "category";
  const [medicines, setMedicines] = useState([]);
  const [categories, setCategories] = useState(["全部"]);
  const [activeCategory, setActiveCategory] = useState("全部");
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
        setCategories(data.categories || ["全部"]);
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
    const nextCategory =
      focusedMedicine?.category || (categories.includes(focus.category) ? focus.category : "全部");
    const nextMedicines =
      nextCategory === "全部"
        ? medicines
        : medicines.filter((medicine) => medicine.category === nextCategory);
    setActiveCategory(nextCategory);
    setViewMode("category");
    setSelectedMedicine(focusedMedicine || nextMedicines[0] || medicines[0] || null);
  }, [categories, focus, medicines]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("dispenseModal") === "1" && selectedMedicine) {
      setModalOpen(true);
    }
  }, [selectedMedicine]);

  const filteredMedicines = useMemo(() => {
    if (activeCategory === "全部") {
      return medicines;
    }
    return medicines.filter((medicine) => medicine.category === activeCategory);
  }, [activeCategory, medicines]);

  const visibleMedicines = filteredMedicines.slice(0, 6);

  function handleCategoryChange(nextCategory) {
    setActiveCategory(nextCategory);
    const nextMedicines =
      nextCategory === "全部"
        ? medicines
        : medicines.filter((medicine) => medicine.category === nextCategory);
    setSelectedMedicine(nextMedicines[0] || null);
  }

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
                className={viewMode === "category" ? "active" : ""}
                onClick={() => setViewMode("category")}
              >
                分类
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

        {viewMode === "category" ? (
          <CategoryTabs categories={categories} activeCategory={activeCategory} onChange={handleCategoryChange} />
        ) : null}

        {viewMode === "category" ? (
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
          {viewMode === "category"
            ? `当前显示 ${visibleMedicines.length}/${filteredMedicines.length} 种，切换分类查看更多药品。`
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
