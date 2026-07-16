import React, { useState } from "react";
import { MonitorOff, MonitorUp, Power, RefreshCw, RotateCw, ServerCog, ShieldAlert } from "lucide-react";
import { runAdminSystemAction } from "../../api/admin.js";
import { AdminConfirmDialog } from "./AdminConfirmDialog.jsx";

const actions = [
  { id: "screen_on", title: "唤醒屏幕", description: "向当前显示输出发送唤醒指令。", expected: "SCREEN ON", icon: MonitorUp, tone: "primary" },
  { id: "screen_off", title: "关闭屏幕", description: "关闭当前显示输出，触摸或键盘可再次唤醒。", expected: "SCREEN OFF", icon: MonitorOff, tone: "warning" },
  { id: "restart_app", title: "重启应用", description: "重新启动 FastAPI 与前端服务，不重启整机。", expected: "RESTART APP", icon: RotateCw, tone: "warning" },
  { id: "reboot", title: "重启设备", description: "重启主机，当前服务会短暂中断。", expected: "REBOOT DEVICE", icon: Power, tone: "danger" }
];

function deviceLabel(value) {
  if (value?.ok) return "可用";
  if (value?.status === "configured") return "已配置";
  return "暂不可用";
}

export function AdminDevices({ overview, loading, onRefresh, notify, onSessionExpired }) {
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false);
  const devices = overview?.devices || {};
  const rows = [
    ["外设网关", devices.gateway],
    ["摄像头", devices.camera],
    ["人脸识别", devices.face],
    ["指纹模块", devices.fingerprint],
    ["麦克风", devices.microphone]
  ];

  function execute(value) {
    setBusy(true);
    runAdminSystemAction(pending.id, value)
      .then((result) => {
        notify(result.message || (result.accepted ? "操作已接受" : "系统操作失败"));
        if (result.ok && result.accepted) setPending(null);
      })
      .catch((error) => {
        if (/会话/.test(error.message || "")) onSessionExpired();
        notify(error.message || "系统操作失败");
      })
      .finally(() => setBusy(false));
  }

  return (
    <div className="admin-view admin-devices-view">
      <div className="admin-page-heading">
        <div><h2>设备控制</h2><p>查看外设状态并执行受保护的主机操作</p></div>
        <button type="button" className="admin-button secondary compact" onClick={onRefresh} disabled={loading}><RefreshCw size={17} />重新检查</button>
      </div>
      <section className="admin-device-status-panel">
        <header><ServerCog size={20} /><h3>外设检查</h3><span>{overview?.generated_at || ""}</span></header>
        <div className="admin-device-table">
          {rows.map(([label, value]) => (
            <div key={label}><span className={`admin-status-dot ${value?.ok ? "ok" : "warn"}`} /><strong>{label}</strong><span>{deviceLabel(value)}</span><code>{value?.status || (value?.ok ? "ready" : "unavailable")}</code></div>
          ))}
        </div>
      </section>
      <section className="admin-system-actions">
        <header><ShieldAlert size={20} /><div><h3>系统操作</h3><p>每次执行都需要输入确认文本并写入审计日志</p></div></header>
        <div>
          {actions.map(({ icon: Icon, ...action }) => (
            <button key={action.id} type="button" className={`admin-system-action ${action.tone}`} onClick={() => setPending(action)}>
              <span><Icon size={21} /></span><div><strong>{action.title}</strong><small>{action.description}</small></div>
            </button>
          ))}
        </div>
      </section>
      <AdminConfirmDialog open={Boolean(pending)} title={pending?.title} description={pending?.description} expected={pending?.expected || ""} confirmLabel="确认执行" tone={pending?.tone} busy={busy} onCancel={() => setPending(null)} onConfirm={execute} />
    </div>
  );
}
