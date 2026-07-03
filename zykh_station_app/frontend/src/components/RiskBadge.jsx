import React from "react";

export function RiskBadge({ level, label }) {
  return <span className={`risk-badge ${level || "idle"}`}>{label || "待评估"}</span>;
}
