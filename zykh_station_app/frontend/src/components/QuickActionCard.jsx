import React from "react";
import { Camera, ClipboardList, PackageCheck } from "lucide-react";

const icons = {
  scan: Camera,
  medicines: PackageCheck,
  records: ClipboardList
};

export function QuickActionCard({ action, onSelect }) {
  const Icon = icons[action.id] || PackageCheck;
  return (
    <button className={`quick-action ${action.tone || "blue"}`} type="button" onClick={() => onSelect(action)}>
      <span className="quick-icon" aria-hidden="true">
        <Icon size={38} strokeWidth={2.2} />
      </span>
      <span>
        <strong>{action.title}</strong>
        <small>{action.subtitle}</small>
      </span>
    </button>
  );
}
