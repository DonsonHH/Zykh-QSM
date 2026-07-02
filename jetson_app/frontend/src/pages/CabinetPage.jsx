import { Boxes, ShieldCheck, Tag } from "lucide-react";
import React, { useMemo, useState } from "react";
import { GlassCard } from "../components/GlassCard.jsx";
import { MedicineSlot } from "../components/MedicineSlot.jsx";
import { medicineForSlot, slotLayout, slotLabel, stockState } from "../utils/domain.js";

const filters = [
  { id: "all", label: "全部" },
  { id: "感冒发热", label: "感冒发热" },
  { id: "肠胃", label: "肠胃" },
  { id: "过敏", label: "过敏" },
  { id: "外伤消毒", label: "外伤消毒" },
  { id: "慢病常用", label: "慢病常用" }
];

export function CabinetPage({ medicines, setPage }) {
  const [selected, setSelected] = useState(1);
  const [filter, setFilter] = useState("all");
  const selectedMedicine = medicineForSlot(medicines, selected);

  const visibleSlots = useMemo(() => {
    if (filter === "all") return slotLayout;
    return slotLayout.filter((slot) => {
      const med = medicineForSlot(medicines, slot.slot);
      return med.category === filter || String(med.indication_tags || "").includes(filter);
    });
  }, [filter, medicines]);

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

  return (
    <div className="cabinet-page">
      <GlassCard className="cabinet-main">
        <div className="page-heading compact">
          <div>
            <span className="card-eyebrow">可用药品 / 应急药品库存</span>
            <h1>23 仓库存总览</h1>
          </div>
          <div className="heading-pill">#{selected} · {slotLabel(selected)}</div>
        </div>
        <div className="cabinet-tabs category-tabs">
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

      <GlassCard className="slot-editor public-medicine-detail">
        <div className="editor-head">
          <div>
            <span className="card-eyebrow">药品安全核验</span>
            <h2>{selectedMedicine.name || `${String(selected).padStart(2, "0")} 号空仓`}</h2>
          </div>
          <Boxes size={42} />
        </div>
        <InfoRow icon={Tag} label="类别" value={selectedMedicine.category || "其他应急"} />
        <InfoRow icon={ShieldCheck} label="用途标签" value={selectedMedicine.indication_tags || "待管理员维护"} />
        <InfoRow icon={ShieldCheck} label="禁忌提醒" value={selectedMedicine.contraindications || "请核对说明书、过敏史和重复用药风险"} />
        <InfoRow icon={Tag} label="库存" value={`${selectedMedicine.stock || 0} ${selectedMedicine.unit || "件"} · 有效期 ${selectedMedicine.expire_date || "--"}`} />
        <div className="safety-note-box">
          <strong>安全提示</strong>
          <span>{selectedMedicine.safety_note || "普通用户端只展示库存和核验信息，药品维护与设备控制由管理员在后台完成。"}</span>
        </div>
        <button className="primary wide" onClick={() => setPage("ai")}>从 AI 应急问询进入取药确认</button>
        <span className="qsm-note">低风险且无明显禁忌时才允许用户确认取药；其他情况需要管理员复核。</span>
      </GlassCard>
    </div>
  );
}

function InfoRow({ icon: Icon, label, value }) {
  return (
    <div className="info-row">
      <Icon size={20} />
      <span>{label}</span>
      <strong>{value}</strong>
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
