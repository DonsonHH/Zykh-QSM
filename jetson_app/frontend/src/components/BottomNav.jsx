import React from "react";
import { Bot, Camera, ClipboardList, Home, Package2 } from "lucide-react";

const navItems = [
  { id: "home", label: "首页", icon: Home },
  { id: "cabinet", label: "药品", icon: Package2 },
  { id: "scan", label: "扫码", icon: Camera },
  { id: "ai", label: "问询", icon: Bot },
  { id: "profile", label: "记录", icon: ClipboardList }
];

export function BottomNav({ page, onChange }) {
  return (
    <nav className="bottom-nav" aria-label="终端导航">
      {navItems.map(({ id, label, icon: Icon }) => (
        <button key={id} className={page === id ? "active" : ""} onClick={() => onChange(id)}>
          <Icon size={24} />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}
