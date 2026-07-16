import React from "react";
import { AlertTriangle, X } from "lucide-react";

export function AdminConfirmDialog({ open, title, description, expected, confirmLabel, tone = "danger", busy, onCancel, onConfirm }) {
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
        <div className="admin-confirm-summary">确认后将立即执行此操作，并写入管理员审计记录。</div>
        <footer>
          <button type="button" className="admin-button secondary" onClick={onCancel}>取消</button>
          <button
            type="button"
            className={`admin-button ${tone === "danger" ? "danger" : "primary"}`}
            autoFocus
            disabled={busy}
            onClick={() => onConfirm(expected)}
          >
            {busy ? "正在执行" : confirmLabel}
          </button>
        </footer>
      </section>
    </div>
  );
}
