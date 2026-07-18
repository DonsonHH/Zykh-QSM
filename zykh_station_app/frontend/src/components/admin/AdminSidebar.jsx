import React from "react";
import { Activity, Boxes, CalendarClock, ClipboardList, LayoutDashboard, LogOut, MessagesSquare, Settings2, UsersRound, X } from "lucide-react";
import { BrandLogoImage } from "../BrandLogoImage.jsx";

const sections = [
  { id: "overview", label: "运行概览", icon: LayoutDashboard },
  { id: "users", label: "服务对象", icon: UsersRound },
  { id: "plans", label: "今日用药", icon: CalendarClock },
  { id: "cabinet", label: "药柜维护", icon: Boxes },
  { id: "devices", label: "设备控制", icon: Activity },
  { id: "inquiries", label: "问询调试", icon: MessagesSquare },
  { id: "logs", label: "运行日志", icon: ClipboardList }
];

export function AdminSidebar({ active, onChange, onExit, onLogout }) {
  return (
    <aside className="admin-sidebar">
      <div className="admin-sidebar-brand">
        <BrandLogoImage className="admin-brand-image" />
        <div>
          <strong>智药康护</strong>
          <span>设备调试台</span>
        </div>
      </div>
      <nav aria-label="管理员功能">
        {sections.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" className={active === id ? "active" : ""} onClick={() => onChange(id)}>
            <Icon size={19} aria-hidden="true" />
            <span>{label}</span>
          </button>
        ))}
      </nav>
      <div className="admin-sidebar-meta">
        <Settings2 size={17} aria-hidden="true" />
        <span>受保护的本机管理会话</span>
      </div>
      <div className="admin-sidebar-actions">
        <button type="button" onClick={onExit}>
          <X size={18} aria-hidden="true" />
          返回终端
        </button>
        <button type="button" onClick={onLogout}>
          <LogOut size={18} aria-hidden="true" />
          退出登录
        </button>
      </div>
    </aside>
  );
}
