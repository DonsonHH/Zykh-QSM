import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { LoaderCircle, ScanLine } from "lucide-react";
import { assessManualMedication, confirmManualMedication } from "../api/dispense.js";
import { loadMedicine, loadMedicines } from "../api/medicines.js";
import { CabinetSlotMap } from "../components/CabinetSlotMap.jsx";
import { DispenseConfirmModal } from "../components/DispenseConfirmModal.jsx";
import { MedicineCard } from "../components/MedicineCard.jsx";
import { MedicineDetailPanel } from "../components/MedicineDetailPanel.jsx";
import { projectMedicinesToCabinets } from "../utils/cabinetV2.js";
import { normalizeCabinetLightMessage } from "../utils/cabinetLightPresentation.js";
import { manualDispenseBlockReason } from "../utils/medicineSafety.js";

function VirtualMedicineGrid({ medicines, selectedMedicine, onSelect }) {
  const gridRef = useRef(null);
  const [viewport, setViewport] = useState({ height: 320, scrollTop: 0, rowHeight: 80, gap: 12 });
  const [renderedRowCount, setRenderedRowCount] = useState(1);

  useEffect(() => {
    const grid = gridRef.current;
    if (!grid) return undefined;
    const measure = () => {
      const styles = getComputedStyle(grid);
      setViewport((current) => ({
        ...current,
        height: grid.clientHeight,
        rowHeight: Number.parseFloat(styles.getPropertyValue("--medicine-grid-row-height")) || 80,
        gap: Number.parseFloat(styles.getPropertyValue("--medicine-grid-gap")) || 12
      }));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(grid);
    return () => observer.disconnect();
  }, []);

  const stride = viewport.rowHeight + viewport.gap;
  const totalRows = Math.ceil(medicines.length / 2);
  const firstRow = Math.max(0, Math.floor(viewport.scrollTop / stride) - 1);
  const lastRow = Math.min(totalRows, Math.ceil((viewport.scrollTop + viewport.height) / stride) + 1);
  const renderedLastRow = Math.min(lastRow, firstRow + renderedRowCount);
  const visibleMedicines = medicines.slice(firstRow * 2, renderedLastRow * 2);

  useEffect(() => {
    if (renderedLastRow >= lastRow) return undefined;
    const frame = window.requestAnimationFrame(() => {
      setRenderedRowCount((current) => Math.min(lastRow - firstRow, current + 1));
    });
    return () => window.cancelAnimationFrame(frame);
  }, [firstRow, lastRow, renderedLastRow]);

  useLayoutEffect(() => {
    const grid = gridRef.current;
    const selectedIndex = medicines.findIndex((medicine) => medicine.id === selectedMedicine?.id);
    if (!grid || selectedIndex < 0) return;
    const row = Math.floor(selectedIndex / 2);
    const rowTop = row * stride;
    const rowBottom = rowTop + viewport.rowHeight;
    const viewportTop = grid.scrollTop;
    const viewportBottom = viewportTop + grid.clientHeight;
    let nextScrollTop = viewportTop;
    if (rowTop < viewportTop) nextScrollTop = rowTop;
    else if (rowBottom > viewportBottom) nextScrollTop = rowBottom - grid.clientHeight;
    nextScrollTop = Math.max(0, Math.min(nextScrollTop, grid.scrollHeight - grid.clientHeight));
    if (Math.abs(nextScrollTop - viewportTop) < 1) return;
    grid.scrollTop = nextScrollTop;
    setViewport((current) => ({ ...current, scrollTop: nextScrollTop }));
  }, [medicines, selectedMedicine?.id, stride, viewport.height, viewport.rowHeight]);

  function visibleRange(scrollTop, currentViewport = viewport) {
    const currentStride = currentViewport.rowHeight + currentViewport.gap;
    return {
      first: Math.max(0, Math.floor(scrollTop / currentStride) - 1),
      last: Math.min(
        totalRows,
        Math.ceil((scrollTop + currentViewport.height) / currentStride) + 1
      )
    };
  }

  function handleScroll(event) {
    const nextScrollTop = event.currentTarget.scrollTop;
    setViewport((current) => {
      const currentRange = visibleRange(current.scrollTop, current);
      const nextRange = visibleRange(nextScrollTop, current);
      if (currentRange.first === nextRange.first && currentRange.last === nextRange.last) {
        return current;
      }
      return { ...current, scrollTop: nextScrollTop };
    });
  }

  function handleOptionKeyDown(event, index) {
    let nextIndex = index;
    if (event.key === "ArrowRight") nextIndex += 1;
    else if (event.key === "ArrowLeft") nextIndex -= 1;
    else if (event.key === "ArrowDown") nextIndex += 2;
    else if (event.key === "ArrowUp") nextIndex -= 2;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = medicines.length - 1;
    else return;
    event.preventDefault();
    nextIndex = Math.max(0, Math.min(nextIndex, medicines.length - 1));
    if (nextIndex === index) return;
    onSelect(medicines[nextIndex]);
    window.requestAnimationFrame(() => {
      gridRef.current?.querySelector(`[data-medicine-index="${nextIndex}"]`)?.focus();
    });
  }

  return (
    <div
      className="medicine-grid"
      ref={gridRef}
      role="listbox"
      aria-label="药品列表"
      onScroll={handleScroll}
    >
      <div
        className="medicine-grid-virtual-space"
        style={{ height: Math.max(viewport.rowHeight, totalRows * stride - viewport.gap) }}
      >
        {visibleMedicines.map((medicine, visibleIndex) => {
          const index = firstRow * 2 + visibleIndex;
          const row = Math.floor(index / 2);
          return (
            <MedicineCard
              key={medicine.id}
              className={`virtual-card ${index % 2 ? "right" : "left"}`}
              style={{ top: row * stride, height: viewport.rowHeight }}
              medicine={medicine}
              selected={selectedMedicine?.id === medicine.id}
              onSelect={onSelect}
              index={index}
              onKeyDown={(event) => handleOptionKeyDown(event, index)}
              position={index + 1}
              total={medicines.length}
            />
          );
        })}
      </div>
    </div>
  );
}

export function Medicines({ notify, focus, onNavigate }) {
  const initialParams = new URLSearchParams(window.location.search);
  const initialMedicineView = initialParams.get("medicineView") === "cabinet" ? "cabinet" : "list";
  const initialMedicineId = initialParams.get("medicineId");
  const [medicines, setMedicines] = useState([]);
  const [cabinets, setCabinets] = useState([]);
  const [selectedMedicine, setSelectedMedicine] = useState(null);
  const [confirmMedicine, setConfirmMedicine] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [modalResult, setModalResult] = useState("");
  const [modalError, setModalError] = useState("");
  const [viewMode, setViewMode] = useState(initialMedicineView);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [detailMedicine, setDetailMedicine] = useState(null);

  useEffect(() => {
    setLoading(true);
    setLoadError("");
    loadMedicines()
      .then((data) => {
        const loadedCabinets = data.cabinets || [];
        const loadedMedicines = projectMedicinesToCabinets(data.medicines || [], loadedCabinets);
        setCabinets(loadedCabinets);
        setMedicines(loadedMedicines);
        setSelectedMedicine(
          loadedMedicines.find((medicine) => medicine.id === initialMedicineId) || loadedMedicines[0] || null
        );
        setLoading(false);
      })
      .catch((error) => {
        const message = error.message || "药品列表加载失败";
        setLoadError(message);
        notify(message);
        setLoading(false);
      });
  }, [notify]);

  useEffect(() => {
    const updateInventory = (event) => {
      const updated = event.detail;
      if (!updated?.id) return;
      const projected = projectMedicinesToCabinets([updated], cabinets)[0];
      setMedicines((items) => items.map((item) => item.id === projected.id ? projected : item));
      setSelectedMedicine((current) => current?.id === projected.id ? projected : current);
      notify(
        updated.inventory_state === "DEPLETED"
          ? `${projected.cabinet_id}号分类柜的${updated.name}已标记为缺药`
          : `${projected.cabinet_id}号分类柜的${updated.name}库存已确认`
      );
    };
    window.addEventListener("zykh:medicine-updated", updateInventory);
    return () => window.removeEventListener("zykh:medicine-updated", updateInventory);
  }, [cabinets, notify]);

  useEffect(() => {
    const refreshDispenseHistory = (event) => {
      const medicineId = event.detail?.medicine_id;
      if (!medicineId) return;
      loadMedicine(medicineId)
        .then((response) => {
          const updated = projectMedicinesToCabinets([response.medicine], cabinets)[0];
          if (!updated?.id) return;
          setMedicines((items) => items.map((item) => item.id === updated.id ? updated : item));
          setSelectedMedicine((current) => current?.id === updated.id ? updated : current);
          setDetailMedicine((current) => current?.id === updated.id ? updated : current);
          setConfirmMedicine((current) => current?.id === updated.id ? updated : current);
        })
        .catch(() => undefined);
    };
    window.addEventListener("zykh:dispense-recorded", refreshDispenseHistory);
    return () => window.removeEventListener("zykh:dispense-recorded", refreshDispenseHistory);
  }, [cabinets]);

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
      const blockReason = manualDispenseBlockReason(selectedMedicine);
      if (blockReason) {
        setModalOpen(false);
        notify(blockReason);
        return;
      }
      setConfirmMedicine(selectedMedicine);
      setModalOpen(true);
    }
  }, [notify, selectedMedicine]);

  useEffect(() => {
    let secondFrame = 0;
    const firstFrame = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => setDetailMedicine(selectedMedicine));
    });
    return () => {
      window.cancelAnimationFrame(firstFrame);
      window.cancelAnimationFrame(secondFrame);
    };
  }, [selectedMedicine]);

  const stockedCount = useMemo(() => medicines.filter((medicine) => medicine.stock > 0).length, [medicines]);
  const unassignedCount = useMemo(
    () => medicines.filter((medicine) => medicine.cabinet_unassigned || !medicine.cabinet_id).length,
    [medicines]
  );
  const stockedCabinetCount = useMemo(
    () => cabinets.filter((cabinet) => cabinet.medicine_ids.some(
      (medicineId) => medicines.some((medicine) => medicine.id === medicineId && medicine.stock > 0)
    )).length,
    [cabinets, medicines]
  );

  function openConfirm() {
    if (!detailMedicine) {
      notify("请先选择药品");
      return;
    }
    const blockReason = manualDispenseBlockReason(detailMedicine);
    if (blockReason) {
      notify(blockReason);
      return;
    }
    setModalResult("");
    setModalError("");
    setConfirmMedicine(detailMedicine);
    setModalOpen(true);
  }

  function handleManualAssessment(payload) {
    setSubmitting(true);
    setModalError("");
    return assessManualMedication(payload)
      .catch((error) => {
        setModalError(error.message || "个人用药安全核查失败");
        throw error;
      })
      .finally(() => setSubmitting(false));
  }

  function handleManualConfirmation(payload) {
    setSubmitting(true);
    setModalError("");
    return confirmManualMedication(payload)
      .then((data) => {
        const message = normalizeCabinetLightMessage(data.message);
        notify(message);
        if (data.dispense_status === "DISPENSED") {
          setModalResult(message);
          window.dispatchEvent(new CustomEvent("zykh:dispense-recorded", {
            detail: { medicine_id: confirmMedicine?.id || payload.medicine_id }
          }));
        }
        return data;
      })
      .catch((error) => {
        setModalError(error.message || "取药确认失败");
        throw error;
      })
      .finally(() => setSubmitting(false));
  }

  return (
    <main className="medicines-page">
      <section className={`medicines-main-panel ${viewMode === "cabinet" ? "cabinet-mode" : ""} ${unassignedCount ? "has-unassigned" : ""}`}>
        <div className="medicines-heading">
          <h2 className="page-entry-cue">药品与分类柜</h2>
          <div className="medicines-heading-actions">
            <span className="medicines-stock-summary">
              {loading ? "读取中" : `${stockedCabinetCount}/3 分类柜 · ${stockedCount} 种在库`}
            </span>
            <div className="medicine-view-toggle" aria-label="药品显示方式">
              <button
                type="button"
                className={viewMode === "list" ? "active" : ""}
                onClick={() => setViewMode("list")}
              >
                药品
              </button>
              <button
                type="button"
                className={viewMode === "cabinet" ? "active" : ""}
                onClick={() => setViewMode("cabinet")}
              >
                分类柜
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

        {unassignedCount ? (
          <div className="medicine-cabinet-warning" role="alert">
            <strong>{unassignedCount} 种药品尚未配置分类柜，已禁止取药。</strong>
            <span>请先完成分类柜映射；可切换到“药品”列表查看这些记录。</span>
          </div>
        ) : null}

        {loading ? (
          <div className="medicine-loading-state" role="status">
            <LoaderCircle className="localized-loader" size={36} aria-hidden="true" />
            <strong>正在读取本地药品</strong>
            <small>请稍候</small>
          </div>
        ) : loadError ? (
          <div className="medicine-loading-state error" role="alert">
            <strong>本地药品读取失败</strong>
            <small>{loadError}</small>
          </div>
        ) : viewMode === "list" ? (
          <VirtualMedicineGrid
            medicines={medicines}
            selectedMedicine={selectedMedicine}
            onSelect={setSelectedMedicine}
          />
        ) : (
          <CabinetSlotMap
            cabinets={cabinets}
            medicines={medicines}
            selectedMedicine={selectedMedicine}
            onSelect={setSelectedMedicine}
          />
        )}

      </section>

      <MedicineDetailPanel medicine={detailMedicine} onConfirm={openConfirm} />

      <DispenseConfirmModal
        medicine={confirmMedicine}
        manualAccess
        open={modalOpen}
        submitting={submitting}
        result={modalResult}
        error={modalError}
        onCancel={() => setModalOpen(false)}
        onAssessManual={handleManualAssessment}
        onConfirmManual={handleManualConfirmation}
      />
    </main>
  );
}
