import React, { useEffect, useMemo, useState } from "react";
import { Lightbulb, Package, RefreshCw, Save } from "lucide-react";
import { loadAdminMedicines, updateAdminMedicine } from "../../api/admin.js";
import { loadMedicines } from "../../api/medicines.js";
import { describeMedicineCabinet } from "../../utils/cabinetLightPresentation.js";

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

const FALLBACK_CABINETS = [
  { id: 1, label: "一类药品", description: "分类名称待配置", medicine_ids: [] },
  { id: 2, label: "二类药品", description: "分类名称待配置", medicine_ids: [] },
  { id: 3, label: "三类药品", description: "分类名称待配置", medicine_ids: [] }
];

function mergeCabinetProjection(adminMedicines, projectedMedicines) {
  const projectionById = new Map(
    (projectedMedicines || []).map((medicine) => [medicine.id, medicine])
  );
  return (adminMedicines || []).map((medicine) => {
    const projection = projectionById.get(medicine.id);
    const cabinetId = Number(projection?.cabinet_id);
    const assigned = Number.isInteger(cabinetId) && cabinetId >= 1 && cabinetId <= 3;
    return {
      ...medicine,
      cabinet_id: assigned ? cabinetId : null,
      cabinet_label: assigned ? projection?.cabinet_label : "分类柜待配置",
      cabinet_description: assigned
        ? projection?.cabinet_description
        : "该药品尚未配置分类柜，暂不能取药。",
      cabinet_unassigned: !assigned
    };
  });
}

export function AdminCabinet({ notify, onSessionExpired }) {
  const [medicines, setMedicines] = useState([]);
  const [cabinets, setCabinets] = useState(FALLBACK_CABINETS);
  const [selectedCabinetId, setSelectedCabinetId] = useState(1);
  const [selectedMedicineId, setSelectedMedicineId] = useState("");
  const [form, setForm] = useState(EMPTY_MEDICINE);
  const [busy, setBusy] = useState(false);
  const cabinetMedicines = useMemo(
    () => medicines.filter((medicine) => medicine.cabinet_id === selectedCabinetId),
    [medicines, selectedCabinetId]
  );
  const unassignedMedicines = useMemo(
    () => medicines.filter((medicine) => medicine.cabinet_unassigned || !medicine.cabinet_id),
    [medicines]
  );
  const selected = useMemo(
    () => medicines.find((medicine) => medicine.id === selectedMedicineId) || cabinetMedicines[0] || null,
    [cabinetMedicines, medicines, selectedMedicineId]
  );

  function handleError(error) {
    if (/会话/.test(error.message || "")) onSessionExpired();
    notify(error.message || "操作失败");
  }

  function refresh() {
    return Promise.all([loadAdminMedicines(), loadMedicines()])
      .then(([adminData, publicData]) => {
        const nextMedicines = mergeCabinetProjection(adminData.medicines, publicData.medicines);
        const nextCabinets = publicData.cabinets?.length === 3 ? publicData.cabinets : FALLBACK_CABINETS;
        const nextCabinetId = nextCabinets.some((cabinet) => cabinet.id === selectedCabinetId)
          ? selectedCabinetId
          : nextCabinets[0].id;
        const nextSelected = nextMedicines.find((medicine) => (
          medicine.id === selectedMedicineId && medicine.cabinet_id === nextCabinetId
        )) || nextMedicines.find((medicine) => medicine.cabinet_id === nextCabinetId);
        setCabinets(nextCabinets);
        setMedicines(nextMedicines);
        setSelectedCabinetId(nextCabinetId);
        setSelectedMedicineId(nextSelected?.id || "");
      })
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
  }, [selected?.id]);

  function selectCabinet(cabinetId) {
    setSelectedCabinetId(cabinetId);
    setSelectedMedicineId(medicines.find((medicine) => medicine.cabinet_id === cabinetId)?.id || "");
  }

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
      .then((data) => {
        setMedicines((current) => mergeCabinetProjection(data.medicines, current));
        notify("药品与库存信息已保存");
      })
      .catch(handleError)
      .finally(() => setBusy(false));
  }

  return (
    <div className="admin-view admin-cabinet-view">
      <div className="admin-page-heading">
        <div className="admin-section-entry-cue">
          <h2>分类柜维护</h2>
          <p>按三个实体分类柜查看和维护本地药品档案</p>
        </div>
        <button type="button" className="admin-button secondary compact" onClick={refresh}>
          <RefreshCw size={17} />刷新
        </button>
      </div>
      <div className="admin-split-view cabinet-split-view">
        <section className="admin-cabinet-grid-panel">
          <header><h3>三个分类柜</h3><span>{medicines.filter((item) => item.stock > 0).length} 种药品有库存</span></header>
          <div className="admin-category-cabinet-grid" role="tablist" aria-label="三个分类柜">
            {cabinets.map((cabinet) => {
              const medicineCount = medicines.filter((medicine) => medicine.cabinet_id === cabinet.id).length;
              return (
                <button
                  key={cabinet.id}
                  type="button"
                  role="tab"
                  aria-selected={cabinet.id === selectedCabinetId}
                  className={cabinet.id === selectedCabinetId ? "active" : ""}
                  onClick={() => selectCabinet(cabinet.id)}
                >
                  <strong>{cabinet.id}<small>号柜</small></strong>
                  <span>{cabinet.label}</span>
                  <em>{medicineCount} 种药品</em>
                </button>
              );
            })}
          </div>
          {unassignedMedicines.length ? (
            <div className="admin-unassigned-medicine-panel" role="group" aria-label="待配置分类柜药品">
              <header>
                <strong>{unassignedMedicines.length} 种药品待配置分类柜</strong>
                <span>完成映射前不可取药</span>
              </header>
              <div>
                {unassignedMedicines.map((medicine) => (
                  <button
                    key={medicine.id}
                    type="button"
                    className={medicine.id === selected?.id ? "active" : ""}
                    onClick={() => setSelectedMedicineId(medicine.id)}
                  >
                    {medicine.name}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <div className="admin-cabinet-medicine-list" role="listbox" aria-label={`${selectedCabinetId}号柜药品`}>
            {cabinetMedicines.map((medicine) => (
              <button
                key={medicine.id}
                type="button"
                role="option"
                aria-selected={medicine.id === selected?.id}
                className={medicine.id === selected?.id ? "active" : ""}
                onClick={() => setSelectedMedicineId(medicine.id)}
              >
                <span><strong>{medicine.name}</strong><small>{medicine.category}</small></span>
                <em>{medicine.stock}{medicine.unit}</em>
              </button>
            ))}
            {!cabinetMedicines.length ? <p className="admin-empty-state">该分类柜暂未配置药品。</p> : null}
          </div>
        </section>
        <section className="admin-editor-panel cabinet-editor-panel">
          <header>
            <div><h3>{selected ? (selected.cabinet_unassigned ? "分类柜待配置" : describeMedicineCabinet(selected)) : `${selectedCabinetId}号柜`}</h3><span>{selected ? selected.id : "请选择药品"}</span></div>
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
                <label><span>药品类别</span><input value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })} /></label>
                <label className="span-two"><span>适用症状</span><textarea value={form.indications} onChange={(event) => setForm({ ...form, indications: event.target.value })} /></label>
                <label className="span-two"><span>用法用量</span><textarea value={form.dosage} onChange={(event) => setForm({ ...form, dosage: event.target.value })} /></label>
                <label className="span-two"><span>禁忌提醒（每行一条）</span><textarea value={form.contraindications} onChange={(event) => setForm({ ...form, contraindications: event.target.value })} /></label>
                <label className="span-two"><span>安全备注</span><textarea value={form.safety_note} onChange={(event) => setForm({ ...form, safety_note: event.target.value })} /></label>
              </div>
              <footer className="admin-editor-actions cabinet-v2-editor-actions">
                <p><Lightbulb size={18} aria-hidden="true" />{selected.cabinet_unassigned ? "该药品尚未映射分类柜，系统已禁止取药。" : "取药时系统会点亮该药所在分类柜，用户自行开柜。"}</p>
                <button type="button" className="admin-button primary" onClick={save} disabled={busy}><Save size={17} />{busy ? "保存中" : "保存信息"}</button>
              </footer>
            </>
          ) : <p className="admin-empty-state">请先在左侧分类柜中选择一条药品记录。</p>}
        </section>
      </div>
    </div>
  );
}
