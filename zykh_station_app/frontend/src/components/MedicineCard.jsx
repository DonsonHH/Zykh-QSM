import React from "react";
import { MedicineIcon } from "./MedicineIcon.jsx";

export function MedicineCard({ medicine, selected, onSelect }) {
  return (
    <button
      type="button"
      className={`medicine-card ${selected ? "selected" : ""}`}
      onClick={() => onSelect(medicine)}
      aria-pressed={selected}
    >
      <MedicineIcon medicine={medicine} size={30} className="medicine-box" />
      <span className="medicine-card-copy">
        <strong>{medicine.name}</strong>
        <small>{medicine.manufacturer ? `${medicine.manufacturer} · ${medicine.category}` : medicine.category}</small>
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
