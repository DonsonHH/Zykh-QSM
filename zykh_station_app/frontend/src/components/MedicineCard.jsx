import React from "react";
import { MedicineIcon } from "./MedicineIcon.jsx";

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
      <span className="medicine-card-meta">
        <em>
          <b>{medicine.hardware_slot || medicine.slot}</b>
          <small>号</small>
        </em>
      </span>
    </button>
  );
}
