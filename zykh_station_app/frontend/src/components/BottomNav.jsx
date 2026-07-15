import React, { useState } from "react";
import { ClipboardList, Home, MessageCircleHeart, Pill } from "lucide-react";
import { StrokeDrawIcon } from "./StrokeDrawIcon.jsx";

const items = [
  { id: "home", label: "首页", icon: Home },
  { id: "medicines", label: "药品", icon: Pill },
  { id: "inquiry", label: "问询", icon: MessageCircleHeart },
  { id: "records", label: "记录", icon: ClipboardList }
];

export function BottomNav({ page, onChange }) {
  const [animation, setAnimation] = useState({ id: "", token: 0 });

  function selectItem(id) {
    setAnimation((current) => ({ id, token: current.token + 1 }));
    onChange(id);
  }

  return (
    <nav className="bottom-nav" aria-label="主导航">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <button
            key={item.id}
            type="button"
            className={page === item.id ? "active" : ""}
            onClick={() => selectItem(item.id)}
            aria-current={page === item.id ? "page" : undefined}
          >
            <span className="bottom-nav-icon" key={animation.id === item.id ? `${item.id}-${animation.token}` : item.id}>
              <StrokeDrawIcon icon={Icon} size={27} strokeWidth={2.1} mode="once" active={animation.id === item.id} />
            </span>
            <span>{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
