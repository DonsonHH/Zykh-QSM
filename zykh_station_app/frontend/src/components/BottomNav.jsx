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
  const [replayKey, setReplayKey] = useState({ id: page, token: 0 });

  function selectPage(id) {
    setReplayKey((current) => ({ id, token: current.token + 1 }));
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
            onClick={() => selectPage(item.id)}
            aria-current={page === item.id ? "page" : undefined}
          >
            <span className="bottom-nav-icon" aria-hidden="true">
              <StrokeDrawIcon
                icon={Icon}
                size={27}
                strokeWidth={2.1}
                mode="once"
                active={page === item.id}
                replayKey={replayKey.id === item.id ? replayKey.token : 0}
              />
            </span>
            <span>{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
