import React from "react";

export function StatusPill({ icon: Icon, label, value, tone = "good", detail }) {
  return (
    <div className={`status-pill ${tone}`} title={`${label}：${value}${detail ? `，${detail}` : ""}`}>
      {Icon && <Icon size={22} />}
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        {detail && <small>{detail}</small>}
      </div>
    </div>
  );
}
