import React from "react";
import { Camera, ClipboardList, HeartPulse, PackageCheck } from "lucide-react";

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
          <button
            key={action.id}
            className={`quick-action ${action.tone || "blue"}`}
            type="button"
            onClick={() => onSelect(action)}
          >
            <span className="quick-icon" aria-hidden="true">
              <Icon size={30} strokeWidth={2.1} />
            </span>
            <span className="quick-copy">
              <strong>{action.title}</strong>
              <small>{action.subtitle}</small>
            </span>
          </button>
        );
      })}
    </section>
  );
}
