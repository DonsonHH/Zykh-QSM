import React from "react";

export function DeviceCard({ icon: Icon, title, value, detail, tone = "good" }) {
  return (
    <article className={`device-card ${tone}`}>
      <div>
        <span>{title}</span>
        <strong>{value}</strong>
        {detail && <small>{detail}</small>}
      </div>
      {Icon && <Icon size={48} />}
    </article>
  );
}
