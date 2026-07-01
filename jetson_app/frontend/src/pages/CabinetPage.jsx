import { Boxes, DoorOpen, Plus, Save, Search } from "lucide-react";
import React, { useEffect, useMemo, useState } from "react";
import { api, formBody } from "../api/client.js";
import { GlassCard } from "../components/GlassCard.jsx";
import { MedicineSlot } from "../components/MedicineSlot.jsx";
import { useAsyncAction } from "../hooks/useAsyncAction.js";
import { medicineForSlot, slotLayout, slotLabel, stockState } from "../utils/domain.js";

const filters = [
  { id: "all", label: "全部" },
  { id: "big", label: "大仓 8" },
  { id: "medium", label: "中仓 6" },
  { id: "small", label: "小仓 9" }
];

export function CabinetPage({ status, medicines, refresh, notify }) {
  const [selected, setSelected] = useState(1);
  const [filter, setFilter] = useState("all");
  const [draft, setDraft] = useState({});
  const [planDraft, setPlanDraft] = useState({ time: "08:00", amount: "1片" });
  const selectedMedicine = medicineForSlot(medicines, selected);
  const qsmOnline = Boolean(status?.qsm?.online);

  useEffect(() => {
    setDraft(selectedMedicine);
  }, [selected, medicines]);

  const visibleSlots = useMemo(
    () => (filter === "all" ? slotLayout : slotLayout.filter((item) => item.kind === filter)),
    [filter]
  );

  const counts = useMemo(() => {
    return medicines.reduce(
      (acc, item) => {
        const state = stockState(item.stock);
        acc[state] += 1;
        return acc;
      },
      { good: 0, warn: 0, danger: 0, empty: 23 - medicines.length }
    );
  }, [medicines]);

  const [save, saving] = useAsyncAction(async () => {
    try {
      await api("/api/medicines", formBody({ ...draft, slot: selected }));
      notify(`${selected} 号仓已保存`);
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  });

  const [open, opening] = useAsyncAction(async () => {
    try {
      const data = await api("/api/dispense", formBody({ slot: selected }));
      notify(data.detail || "开仓完成");
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  });

  const [addPlan, addingPlan] = useAsyncAction(async () => {
    try {
      await api("/api/plans", formBody({ slot: selected, time: planDraft.time, amount: planDraft.amount, enabled: 1 }));
      notify(`${selected} 号仓用药计划已添加`);
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  });

  return (
    <div className="cabinet-page">
      <GlassCard className="cabinet-main">
        <div className="page-heading compact">
          <div>
            <span className="card-eyebrow">药柜管理</span>
            <h1>23 个药仓</h1>
          </div>
          <div className="heading-pill">#{selected} · {slotLabel(selected)}</div>
        </div>
        <div className="cabinet-tabs">
          {filters.map((item) => (
            <button key={item.id} className={filter === item.id ? "active" : ""} onClick={() => setFilter(item.id)}>
              {item.label}
            </button>
          ))}
        </div>
        <div className={`medicine-grid ${filter === "all" ? "all" : "filtered"}`}>
          {visibleSlots.map((slot) => (
            <MedicineSlot
              key={slot.slot}
              {...slot}
              medicine={medicineForSlot(medicines, slot.slot)}
              selected={selected === slot.slot}
              onClick={() => setSelected(slot.slot)}
            />
          ))}
        </div>
        <div className="cabinet-legend">
          <Legend tone="good" label={`库存充足 ${counts.good}`} />
          <Legend tone="warn" label={`库存偏低 ${counts.warn}`} />
          <Legend tone="danger" label={`库存不足 ${counts.danger}`} />
          <Legend tone="empty" label={`无库存 ${counts.empty}`} />
        </div>
      </GlassCard>

      <GlassCard className="slot-editor">
        <div className="editor-head">
          <div>
            <span className="card-eyebrow">仓位详情</span>
            <h2>{String(selected).padStart(2, "0")} 号仓</h2>
          </div>
          <Boxes size={42} />
        </div>
        <label>
          药品名称
          <input value={draft.name || ""} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
        </label>
        <label>
          规格剂量
          <input value={draft.dosage || ""} onChange={(event) => setDraft({ ...draft, dosage: event.target.value })} />
        </label>
        <div className="editor-row">
          <label>
            库存数量
            <input type="number" min="0" value={draft.stock || 0} onChange={(event) => setDraft({ ...draft, stock: event.target.value })} />
          </label>
          <label>
            有效期
            <input value={draft.expire_date || ""} onChange={(event) => setDraft({ ...draft, expire_date: event.target.value })} />
          </label>
        </div>
        <div className="editor-actions">
          <button className="primary" onClick={save} disabled={saving}>
            <Save size={20} />
            {saving ? "保存中" : "保存"}
          </button>
          <button onClick={open} disabled={!qsmOnline || opening}>
            <DoorOpen size={20} />
            {opening ? "开仓中" : "开仓"}
          </button>
        </div>
        <div className="plan-editor">
          <span className="card-eyebrow">用药计划</span>
          <div className="editor-row">
            <label>
              时间
              <input value={planDraft.time} onChange={(event) => setPlanDraft({ ...planDraft, time: event.target.value })} />
            </label>
            <label>
              剂量
              <input value={planDraft.amount} onChange={(event) => setPlanDraft({ ...planDraft, amount: event.target.value })} />
            </label>
          </div>
          <button className="wide" onClick={addPlan} disabled={addingPlan}>
            <Plus size={20} />
            {addingPlan ? "添加中" : "添加计划"}
          </button>
        </div>
        <div className="offline-hint">
          <Search size={18} />
          <span>{qsmOnline ? "外设已连接，允许开仓" : "设备连接中，开仓按钮已暂时关闭"}</span>
        </div>
      </GlassCard>
    </div>
  );
}

function Legend({ tone, label }) {
  return (
    <span className={`legend-item ${tone}`}>
      <i />
      {label}
    </span>
  );
}
