import React, { useEffect, useState } from "react";
import { AlertTriangle, X } from "lucide-react";

export function AdminConfirmDialog({ open, title, description, expected, confirmLabel, tone = "danger", busy, onCancel, onConfirm }) {
  const [value, setValue] = useState("");

  useEffect(() => {
    if (open) setValue("");
  }, [open, expected]);

  if (!open) return null;

  return (
    <div className="admin-dialog-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onCancel()}>
      <section className="admin-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="admin-confirm-title">
        <header>
          <div className={`admin-dialog-icon ${tone}`}>
            <AlertTriangle size={22} aria-hidden="true" />
          </div>
          <div>
            <h3 id="admin-confirm-title">{title}</h3>
            <p>{description}</p>
          </div>
          <button type="button" className="admin-icon-button" onClick={onCancel} aria-label="关闭确认窗口">
            <X size={19} aria-hidden="true" />
          </button>
        </header>
        <label>
          <span>输入 <code>{expected}</code> 确认</span>
          <input autoFocus value={value} onChange={(event) => setValue(event.target.value)} spellCheck="false" />
        </label>
        <footer>
          <button type="button" className="admin-button secondary" onClick={onCancel}>取消</button>
          <button
            type="button"
            className={`admin-button ${tone === "danger" ? "danger" : "primary"}`}
            disabled={value !== expected || busy}
            onClick={() => onConfirm(value)}
          >
            {busy ? "正在执行" : confirmLabel}
          </button>
        </footer>
      </section>
    </div>
  );
}
