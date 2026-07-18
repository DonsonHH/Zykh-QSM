import React from "react";
import { ClipboardList, Home, MessageCircleHeart, Pill } from "lucide-react";

const items = [
  { id: "home", label: "首页", icon: Home },
  { id: "medicines", label: "药品", icon: Pill },
  { id: "inquiry", label: "问询", icon: MessageCircleHeart },
  { id: "records", label: "记录", icon: ClipboardList }
];

export function BottomNav({ page, onChange }) {
  return (
    <nav className="bottom-nav" aria-label="主导航">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <button
            key={item.id}
            type="button"
            className={page === item.id ? "active" : ""}
            onClick={() => onChange(item.id)}
            aria-current={page === item.id ? "page" : undefined}
          >
            <span className="bottom-nav-icon" aria-hidden="true">
              <Icon size={27} strokeWidth={2.1} />
            </span>
            <span>{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
