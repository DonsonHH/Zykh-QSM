import React from "react";

export function BigActionButton({ icon: Icon, title, detail, tone = "blue", onClick, disabled, busy = false }) {
  return (
    <button className={`big-action ${tone} ${busy ? "busy" : ""}`} onClick={onClick} disabled={disabled || busy} aria-busy={busy || undefined}>
      {Icon && <Icon size={34} />}
      <span>
        <strong>{title}</strong>
        {detail && <small>{detail}</small>}
      </span>
    </button>
  );
}
