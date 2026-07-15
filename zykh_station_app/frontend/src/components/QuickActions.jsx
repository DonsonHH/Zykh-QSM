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
              <Icon size={36} strokeWidth={2.05} />
            </span>
            <span className="quick-copy">
              <strong>{action.title}</strong>
            </span>
          </button>
        );
      })}
    </section>
  );
}
