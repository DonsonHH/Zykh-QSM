import React from "react";
import { ArrowRight, Camera, ClipboardList, HeartPulse, PackageCheck } from "lucide-react";

const icons = {
  scan: Camera,
  medicines: PackageCheck,
  vitals: HeartPulse,
  records: ClipboardList
};

export function QuickActions({ actions, onSelect }) {
  return (
    <section className="quick-grid" aria-label="快捷入口">
      {(actions || []).map((action) => {
        const Icon = icons[action.id] || PackageCheck;
        return (
          <article key={action.id} className={`quick-action ${action.tone || "blue"}`}>
            <span className="quick-icon" aria-hidden="true">
              <Icon size={36} strokeWidth={2.05} />
            </span>
            <span className="quick-copy">
              <strong>{action.title}</strong>
              {action.subtitle ? <small>{action.subtitle}</small> : null}
            </span>
            <button
              className={`quick-action-cta${action.id === "vitals" ? " vitals-cta" : ""}`}
              type="button"
              onClick={() => onSelect(action)}
              aria-label={`开始${action.title}`}
            >
              <span>{action.id === "vitals" ? "开始测量" : "立即进入"}</span>
              <ArrowRight size={22} aria-hidden="true" />
            </button>
          </article>
        );
      })}
    </section>
  );
}
