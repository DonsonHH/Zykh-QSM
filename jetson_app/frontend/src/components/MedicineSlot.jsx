import React from "react";
import { Package2, Pill, Tablets } from "lucide-react";
import { stockState, stockText } from "../utils/domain.js";

function SlotIcon({ kind }) {
  if (kind === "big") return <Pill size={28} />;
  if (kind === "small") return <Tablets size={28} />;
  return <Package2 size={28} />;
}

export function MedicineSlot({ slot, kind, label, medicine, selected, onClick }) {
  const state = stockState(medicine?.stock);
  return (
    <button className={`medicine-slot ${kind} ${state} ${selected ? "selected" : ""}`} onClick={onClick}>
      <div className="slot-topline">
        <strong>{String(slot).padStart(2, "0")}</strong>
        <span>{label}</span>
      </div>
      <div className="slot-body">
        <SlotIcon kind={kind} />
        <div>
          <b>{medicine?.name || "空仓位"}</b>
          <small>{medicine?.dosage || (state === "empty" ? "等待录入" : "未填规格")}</small>
        </div>
      </div>
      <div className="slot-stock">
        <span>{state === "good" ? "库存充足" : state === "warn" ? "库存偏低" : state === "danger" ? "库存不足" : "无库存"}</span>
        <strong>{stockText(medicine?.stock)}</strong>
      </div>
    </button>
  );
}
