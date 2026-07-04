import React from "react";
import { PackageCheck } from "lucide-react";

export function MedicineCard({ medicine, selected, onSelect }) {
  return (
    <button
      type="button"
      className={`medicine-card ${selected ? "selected" : ""}`}
      onClick={() => onSelect(medicine)}
      aria-pressed={selected}
    >
      <span className="medicine-box" aria-hidden="true">
        <PackageCheck size={30} strokeWidth={2.1} />
      </span>
      <span className="medicine-card-copy">
        <strong>{medicine.name}</strong>
        <small>{medicine.category}</small>
      </span>
      <span className="medicine-card-meta">
        <b>
          {medicine.stock}
          {medicine.unit}
        </b>
        <em>{medicine.hardware_slot || medicine.slot}</em>
      </span>
    </button>
  );
}
