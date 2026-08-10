import React, { useEffect, useMemo, useState } from "react";
import { DoorOpen, Package, RefreshCw, Save } from "lucide-react";
import {
  clearAdminCabinetRequestId,
  loadAdminMedicines,
  openAdminCabinet,
  pendingAdminCabinetRequestId,
  updateAdminMedicine
} from "../../api/admin.js";
import { AdminConfirmDialog } from "./AdminConfirmDialog.jsx";

const EMPTY_MEDICINE = {
  name: "",
  manufacturer: "",
  barcode: "",
  stock: 0,
  unit: "盒",
  expire_date: "",
  category: "",
  indications: "",
  dosage: "",
  contraindications: "",
  safety_note: ""
};

export function AdminCabinet({ notify, onSessionExpired }) {
  const [medicines, setMedicines] = useState([]);
  const [selectedSlot, setSelectedSlot] = useState(1);
  const [form, setForm] = useState(EMPTY_MEDICINE);
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const selected = useMemo(() => medicines.find((medicine) => medicine.hardware_slot === selectedSlot) || null, [medicines, selectedSlot]);

  function handleError(error) {
    if (/会话/.test(error.message || "")) onSessionExpired();
    notify(error.message || "操作失败");
  }

  function refresh() {
    return loadAdminMedicines()
      .then((data) => setMedicines(data.medicines || []))
      .catch(handleError);
  }

  useEffect(() => { refresh(); }, []);
  useEffect(() => {
    setForm(selected ? {
      name: selected.name || "",
      manufacturer: selected.manufacturer || "",
      barcode: selected.barcode || "",
      stock: selected.stock ?? 0,
      unit: selected.unit || "盒",
      expire_date: selected.expire_date || "",
      category: selected.category || "",
      indications: selected.indications || "",
      dosage: selected.dosage || "",
      contraindications: (selected.contraindications || []).join("\n"),
      safety_note: selected.safety_note || ""
    } : EMPTY_MEDICINE);
  }, [selected?.id, selectedSlot]);

  function save() {
    if (!selected) return;
    setBusy(true);
    updateAdminMedicine(selected.id, {
      ...form,
      stock: Number(form.stock) || 0,
      contraindications: form.contraindications
        .split(/[\n；;]/)
        .map((item) => item.trim())
        .filter(Boolean)
    })
      .then((data) => { setMedicines(data.medicines || []); notify("药品与库存信息已保存"); })
      .catch(handleError)
      .finally(() => setBusy(false));
  }

  function openDoor(value) {
    setBusy(true);
    const requestId = pendingAdminCabinetRequestId(selectedSlot);
    openAdminCabinet(selectedSlot, value, "管理员调试开柜", requestId)
      .then((result) => {
        notify(result.message || (result.ok ? `${selectedSlot} 号柜已打开` : "开柜失败"));
        if (!result.result_unknown) clearAdminCabinetRequestId(selectedSlot);
        if (result.ok || result.result_unknown) setConfirmOpen(false);
      })
      .catch(handleError)
      .finally(() => setBusy(false));
  }

  return (
    <div className="admin-view admin-cabinet-view">
      <div className="admin-page-heading">
        <div className="admin-section-entry-cue"><h2>药柜维护</h2><p>编辑 1 至 23 号仓位信息并进行现场开柜测试</p></div>
        <button type="button" className="admin-button secondary compact" onClick={refresh}><RefreshCw size={17} />刷新</button>
      </div>
      <div className="admin-split-view cabinet-split-view">
        <section className="admin-cabinet-grid-panel">
          <header><h3>柜体仓位</h3><span>{medicines.filter((item) => item.stock > 0).length} / 23 有库存</span></header>
          <div className="admin-slot-grid" aria-label="药柜仓位">
            {Array.from({ length: 23 }, (_, index) => index + 1).map((slot) => {
              const medicine = medicines.find((item) => item.hardware_slot === slot);
              return (
                <button key={slot} type="button" className={`${slot === selectedSlot ? "active" : ""} ${medicine?.stock > 0 ? "filled" : "empty"}`} onClick={() => setSelectedSlot(slot)}>
                  <strong>{slot}</strong><span>{medicine?.name || "空仓"}</span>
                </button>
              );
            })}
          </div>
        </section>
        <section className="admin-editor-panel cabinet-editor-panel">
          <header>
            <div><h3>{selectedSlot} 号仓</h3><span>{selected ? selected.id : "当前仓位未建立药品记录"}</span></div>
            <Package size={21} aria-hidden="true" />
          </header>
          {selected ? (
            <>
              <div className="admin-form-grid cabinet-editor-grid">
                <label className="span-two"><span>药品名称</span><input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
                <label><span>生产厂家</span><input value={form.manufacturer} onChange={(event) => setForm({ ...form, manufacturer: event.target.value })} /></label>
                <label><span>商品条码</span><input value={form.barcode} onChange={(event) => setForm({ ...form, barcode: event.target.value })} /></label>
                <label><span>库存</span><input type="number" min="0" value={form.stock} onChange={(event) => setForm({ ...form, stock: event.target.value })} /></label>
                <label><span>单位</span><input value={form.unit} onChange={(event) => setForm({ ...form, unit: event.target.value })} /></label>
                <label><span>保质期</span><input value={form.expire_date} onChange={(event) => setForm({ ...form, expire_date: event.target.value })} /></label>
                <label><span>类别</span><input value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })} /></label>
                <label className="span-two"><span>适用症状</span><textarea value={form.indications} onChange={(event) => setForm({ ...form, indications: event.target.value })} /></label>
                <label className="span-two"><span>用法用量</span><textarea value={form.dosage} onChange={(event) => setForm({ ...form, dosage: event.target.value })} /></label>
                <label className="span-two"><span>禁忌提醒（每行一条）</span><textarea value={form.contraindications} onChange={(event) => setForm({ ...form, contraindications: event.target.value })} /></label>
                <label className="span-two"><span>安全备注</span><textarea value={form.safety_note} onChange={(event) => setForm({ ...form, safety_note: event.target.value })} /></label>
              </div>
              <footer className="admin-editor-actions">
                <button type="button" className="admin-button warning" onClick={() => setConfirmOpen(true)} disabled={busy}><DoorOpen size={17} />打开柜门</button>
                <button type="button" className="admin-button primary" onClick={save} disabled={busy}><Save size={17} />{busy ? "保存中" : "保存信息"}</button>
              </footer>
            </>
          ) : <p className="admin-empty-state">该仓位没有药品记录。请通过扫码录入流程建立药品后再维护。</p>}
        </section>
      </div>
      <AdminConfirmDialog
        open={confirmOpen}
        title={`打开 ${selectedSlot} 号柜门`}
        description="请确认现场无人遮挡柜门，操作将立即下发到外设。"
        expected={`OPEN ${selectedSlot}`}
        confirmLabel="确认开柜"
        tone="warning"
        busy={busy}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={openDoor}
      />
    </div>
  );
}
