import React from "react";

const quickSymptoms = ["发热头痛", "咳嗽流涕", "腹泻胃痛", "皮肤过敏", "轻微外伤", "慢病用药"];

export function SymptomQuickChips({ selected, onSelect }) {
  return (
    <div className="symptom-quick-grid" aria-label="常见症状">
      {quickSymptoms.map((symptom) => (
        <button
          key={symptom}
          type="button"
          className={selected === symptom ? "active" : ""}
          onClick={() => onSelect(symptom)}
        >
          {symptom}
        </button>
      ))}
    </div>
  );
}
