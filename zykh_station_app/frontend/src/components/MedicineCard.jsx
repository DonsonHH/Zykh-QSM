import React from "react";
import { MedicineIcon } from "./MedicineIcon.jsx";
import { describeMedicineCabinet } from "../utils/cabinetLightPresentation.js";

export function MedicineCard({
  medicine,
  selected,
  onSelect,
  className = "",
  style,
  index,
  onKeyDown,
  position,
  total
}) {
  return (
    <button
      type="button"
      role="option"
      className={`medicine-card ${className} ${selected ? "selected" : ""}`}
      style={style}
      onClick={() => onSelect(medicine)}
      onKeyDown={onKeyDown}
      tabIndex={selected ? 0 : -1}
      data-medicine-index={index}
      aria-selected={selected}
      aria-posinset={position}
      aria-setsize={total}
    >
      <MedicineIcon medicine={medicine} size={30} className="medicine-box" />
      <span className="medicine-card-copy">
        <strong>{medicine.name}</strong>
        <span className="medicine-card-context">
          {medicine.manufacturer ? <small className="medicine-manufacturer">{medicine.manufacturer}</small> : null}
          <small className="medicine-efficacy">{medicine.category}</small>
        </span>
      </span>
      <span
        className="medicine-card-meta"
        aria-label={medicine.cabinet_id
          ? describeMedicineCabinet(medicine)
          : "分类柜待配置"}
      >
        <em className={medicine.cabinet_id ? "" : "unassigned"}>
          <b>{medicine.cabinet_id || "待"}</b>
          <small>{medicine.cabinet_id ? "号柜" : "配置分类柜"}</small>
        </em>
      </span>
    </button>
  );
}
