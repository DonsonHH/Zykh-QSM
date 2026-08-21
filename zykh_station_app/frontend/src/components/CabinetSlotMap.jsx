import React from "react";
import { groupMedicinesByCabinet } from "../utils/cabinetV2.js";

export function CabinetSlotMap({ cabinets, medicines, selectedMedicine, onSelect }) {
  const groups = groupMedicinesByCabinet(medicines, cabinets);

  return (
    <div className="cabinet-map" role="list" aria-label="三个分类药柜">
      {groups.map((cabinet) => (
        <section
          key={cabinet.id}
          className={`cabinet-group cabinet-group-${cabinet.id}`}
          role="listitem"
          aria-labelledby={`cabinet-group-title-${cabinet.id}`}
        >
          <header className="cabinet-group-heading">
            <span className="cabinet-group-number" aria-hidden="true">{cabinet.id}</span>
            <div>
              <h3 id={`cabinet-group-title-${cabinet.id}`}>{cabinet.id}号柜 · {cabinet.label}</h3>
              <p>{cabinet.description}</p>
            </div>
          </header>
          <div className="cabinet-medicine-list">
            {cabinet.medicines.map((medicine) => {
              const selected = selectedMedicine?.id === medicine.id;
              return (
                <button
                  key={medicine.id}
                  type="button"
                  className={`cabinet-medicine ${selected ? "selected" : ""} ${medicine.stock > 0 ? "" : "depleted"}`}
                  aria-pressed={selected}
                  aria-label={`${cabinet.id}号柜 ${cabinet.label}，${medicine.name}`}
                  onClick={() => onSelect(medicine)}
                >
                  <strong>{medicine.name}</strong>
                  <small>{medicine.category}{medicine.stock > 0 ? "" : " · 暂无库存"}</small>
                </button>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
