import React from "react";

const mediumSlots = [
  [14, 13],
  [12, 11],
  [10, 9]
];

const smallSlots = [
  [23, 22, 21],
  [20, 19, 18],
  [17, 16, 15]
];

const largeSlots = [
  [8, 7, 6, 5],
  [4, 3, 2, 1]
];

export function CabinetSlotMap({ medicines, selectedMedicine, onSelect, notify }) {
  const medicineBySlot = new Map(medicines.map((medicine) => [medicine.hardware_slot, medicine]));

  function renderSlot(slot, size) {
    const medicine = medicineBySlot.get(slot);
    const selected = Boolean(medicine && selectedMedicine?.id === medicine.id);
    return (
      <button
        key={slot}
        type="button"
        className={`cabinet-slot ${size} ${selected ? "selected" : ""} ${medicine ? "" : "empty"}`}
        aria-pressed={selected}
        onClick={() => {
          if (medicine) {
            onSelect(medicine);
            return;
          }
          notify(`${slot}号仓暂无药品`);
        }}
      >
        <span className="cabinet-slot-number">{slot}</span>
        <strong>{medicine?.name || "空仓"}</strong>
        <small>{medicine ? `${medicine.stock}${medicine.unit}` : "待补货"}</small>
      </button>
    );
  }

  function renderZone(title, slots, size) {
    return (
      <section className={`cabinet-zone ${size}`} aria-label={title}>
        <header>{title}</header>
        <div>
          {slots.flatMap((row) => row.map((slot) => renderSlot(slot, size)))}
        </div>
      </section>
    );
  }

  return (
    <div className="cabinet-map" aria-label="药柜 1 到 23 号仓位">
      <div className="cabinet-map-top">
        {renderZone("9-14 中仓", mediumSlots, "medium")}
        {renderZone("15-23 小仓", smallSlots, "small")}
      </div>
      {renderZone("1-8 大仓", largeSlots, "large")}
    </div>
  );
}
