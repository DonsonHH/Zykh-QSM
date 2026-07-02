import { ChevronRight, Info, PackageCheck, ScanLine, ShieldCheck } from "lucide-react";
import React, { useMemo, useState } from "react";
import { GlassCard } from "../components/GlassCard.jsx";

const filters = [
  { id: "all", label: "全部" },
  { id: "慢病常用", label: "慢病常用" },
  { id: "感冒发热", label: "感冒发热" },
  { id: "肠胃", label: "肠胃" },
  { id: "过敏", label: "过敏" }
];

const categoryTone = {
  慢病常用: "blue",
  感冒发热: "purple",
  肠胃: "orange",
  过敏: "green",
  外伤消毒: "cyan"
};

export function CabinetPage({ medicines, setPage }) {
  const stocked = useMemo(() => medicines.filter((item) => Number(item.stock) > 0), [medicines]);
  const [filter, setFilter] = useState("all");
  const filtered = useMemo(() => {
    if (filter === "all") return stocked;
    return stocked.filter((item) => item.category === filter || String(item.indication_tags || "").includes(filter));
  }, [filter, stocked]);
  const [selectedSlot, setSelectedSlot] = useState(() => stocked[0]?.slot || 1);
  const selectedMedicine = stocked.find((item) => Number(item.slot) === Number(selectedSlot)) || filtered[0] || stocked[0] || {};
  const allowUserConfirm = Number(selectedMedicine.stock) > 0 && Number(selectedMedicine.is_emergency) === 1 && selectedMedicine.category !== "慢病常用";

  return (
    <div className="cabinet-page cabinet-reference-page">
      <GlassCard className="medicine-list-panel">
        <div className="medicine-list-head">
          <div className="page-title-with-icon">
            <span className="page-icon"><PackageCheck size={34} /></span>
            <h1>站点药品</h1>
            <strong>{stocked.length}<small>/23 仓有库存</small></strong>
          </div>
          <a className="scan-admin-link" href="/admin?section=scan">
            <ScanLine size={22} />
            扫码识别
          </a>
        </div>
        <div className="cabinet-tabs category-tabs">
          {filters.map((item) => (
            <button key={item.id} className={filter === item.id ? "active" : ""} onClick={() => setFilter(item.id)}>
              {item.label}
            </button>
          ))}
        </div>
        <div className="medicine-card-grid">
          {filtered.slice(0, 6).map((item) => (
            <button
              key={item.slot}
              className={`medicine-product-card ${Number(item.slot) === Number(selectedMedicine.slot) ? "selected" : ""}`}
              onClick={() => setSelectedSlot(item.slot)}
            >
              <span className={`product-box ${categoryTone[item.category] || "blue"}`}>
                <PackageCheck size={46} />
              </span>
              <span className="product-info">
                <strong>{item.name || `${item.slot} 号仓药品`}</strong>
                <em>{item.category || "站点药品"}</em>
              </span>
              <b>{item.stock}<small>{item.unit || "盒"}</small></b>
            </button>
          ))}
        </div>
      </GlassCard>

      <GlassCard className="medicine-detail-panel">
        <div className="detail-title">
          <span className="page-icon"><Info size={34} /></span>
          <h1>药品信息</h1>
        </div>
        <div className="detail-hero">
          <span className={`product-box large ${categoryTone[selectedMedicine.category] || "blue"}`}>
            <PackageCheck size={70} />
          </span>
          <div>
            <h2>{selectedMedicine.name || "请选择药品"}</h2>
            <em>{selectedMedicine.category || "站点药品"}</em>
          </div>
        </div>
        <div className="medicine-detail-table">
          <p><span>类别</span><strong>{selectedMedicine.category || "--"}</strong></p>
          <p><span>适用标签</span><strong>{selectedMedicine.indication_tags || "--"}</strong></p>
          <p><span>禁忌提醒</span><strong>{selectedMedicine.contraindications || "请核对说明书"}</strong></p>
          <p><span>库存</span><strong>{selectedMedicine.stock || 0} {selectedMedicine.unit || "件"}</strong></p>
          <p><span>有效期</span><strong>{selectedMedicine.expire_date || "--"}</strong></p>
        </div>
        <div className="confirm-hint">
          <ShieldCheck size={24} />
          <span>{allowUserConfirm ? "低风险且无明显禁忌时可进入取药确认" : "该药品需要值守员复核后处理"}</span>
        </div>
        <button className="hero-action blue wide touch-ripple" onClick={() => setPage("ai")}>
          进入取药确认
          <ChevronRight size={30} />
        </button>
      </GlassCard>
    </div>
  );
}
