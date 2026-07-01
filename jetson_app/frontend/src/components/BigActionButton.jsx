import React from "react";

export function BigActionButton({ icon: Icon, title, detail, tone = "blue", onClick, disabled }) {
  return (
    <button className={`big-action ${tone}`} onClick={onClick} disabled={disabled}>
      {Icon && <Icon size={34} />}
      <span>
        <strong>{title}</strong>
        {detail && <small>{detail}</small>}
      </span>
    </button>
  );
}
