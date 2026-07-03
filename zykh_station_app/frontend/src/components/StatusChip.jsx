import React from "react";

export function StatusChip({ chip }) {
  return (
    <span className={`status-chip ${chip.tone || "soft"}`}>
      <small>{chip.label}</small>
      <strong>{chip.value}</strong>
    </span>
  );
}
