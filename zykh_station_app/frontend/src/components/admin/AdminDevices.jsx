import React, { useEffect, useState } from "react";
import { KeyRound, LoaderCircle, MonitorOff, MonitorUp, Power, RefreshCw, RotateCw, ServerCog, ShieldAlert, Signal, Timer, UserRound, Wifi } from "lucide-react";
import { issueAdminPairingCode, loadAdminNetwork, loadAdminUsers, runAdminSystemAction, updateAdminNetwork } from "../../api/admin.js";
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

function NetworkSwitch({ checked, busy, label, onChange }) {
  return (
    <button
      type="button"
      className={`admin-network-switch ${checked ? "is-on" : ""}`}
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={busy}
      onClick={() => onChange(!checked)}
    >
      <span aria-hidden="true" />
      {busy ? <LoaderCircle className="admin-spin" size={15} aria-hidden="true" /> : <b>{checked ? "已开启" : "已关闭"}</b>}
    </button>
  );
}

function countdownLabel(seconds) {
  const minutes = Math.floor(seconds / 60);
  const remainder = String(seconds % 60).padStart(2, "0");
  return `${minutes}:${remainder}`;
}

export function AdminDevices({ overview, loading, onRefresh, notify, onSessionExpired }) {
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false);
  const [networkSettings, setNetworkSettings] = useState(null);
  const [networkBusy, setNetworkBusy] = useState("");
  const [pairingUsers, setPairingUsers] = useState([]);
  const [pairingUserId, setPairingUserId] = useState("");
  const [pairingBusy, setPairingBusy] = useState(false);
  const [issuedPairing, setIssuedPairing] = useState(null);
  const [pairingRemaining, setPairingRemaining] = useState(0);
  const issuedPairingScope = (issuedPairing?.service_user_ids || [])
    .map((id) => pairingUsers.find((user) => user.id === id)?.name || id)
    .join("、");
  const devices = overview?.devices || {};
  const network = overview?.network || {};
  const rows = [
    ["外设网关", devices.gateway],
    ["摄像头", devices.camera],
    ["人脸识别", devices.face],
    ["指纹模块", devices.fingerprint],
    ["麦克风", devices.microphone]
  ];

  useEffect(() => {
    loadAdminNetwork()
      .then((result) => setNetworkSettings(result.settings || null))
      .catch((error) => {
        if (/会话/.test(error.message || "")) onSessionExpired();
        notify(error.message || "网络设置读取失败");
      });
  }, [notify, onSessionExpired]);

  useEffect(() => {
    loadAdminUsers()
      .then((result) => {
        const users = Array.isArray(result.users) ? result.users : [];
        setPairingUsers(users);
        setPairingUserId((current) => (
          users.some((user) => user.id === current) ? current : users[0]?.id || ""
        ));
      })
      .catch((error) => {
        if (/会话/.test(error.message || "")) onSessionExpired();
        notify(error.message || "服务对象读取失败");
      });
  }, [notify, onSessionExpired]);

  useEffect(() => {
    if (!issuedPairing?.expires_at) {
      setPairingRemaining(0);
      return undefined;
    }
    const updateCountdown = () => {
      const expiresAt = Date.parse(issuedPairing.expires_at);
      const seconds = Number.isFinite(expiresAt)
        ? Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000))
        : 0;
      setPairingRemaining(seconds);
      if (seconds === 0) setIssuedPairing(null);
    };
    updateCountdown();
    const timer = window.setInterval(updateCountdown, 1000);
    return () => window.clearInterval(timer);
  }, [issuedPairing]);

  function updatePhysicalNetwork(key, enabled) {
    const label = key === "wifi_enabled" ? "Wi-Fi" : "数据网络";
    setNetworkBusy(key);
    updateAdminNetwork({ [key]: enabled })
      .then((result) => {
        setNetworkSettings(result.settings || null);
        const warning = result.warnings?.[0];
        notify(warning || `${label}已${enabled ? "开启" : "关闭"}`);
        onRefresh();
      })
      .catch((error) => {
        if (/会话/.test(error.message || "")) onSessionExpired();
        notify(error.message || `${label}操作失败`);
      })
      .finally(() => setNetworkBusy(""));
  }

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

  function issuePairingCode() {
    if (!pairingUserId) return;
    setPairingBusy(true);
    setIssuedPairing(null);
    issueAdminPairingCode([pairingUserId], 10)
      .then((result) => {
        setIssuedPairing(result);
        notify("家属配对码已生成");
      })
      .catch((error) => {
        if (/会话/.test(error.message || "")) onSessionExpired();
        notify(error.message || "配对码生成失败");
      })
      .finally(() => setPairingBusy(false));
  }

  return (
    <div className="admin-view admin-devices-view">
      <div className="admin-page-heading">
        <div className="admin-section-entry-cue"><h2>设备控制</h2><p>查看外设状态并执行受保护的主机操作</p></div>
        <button type="button" className="admin-button secondary compact" onClick={onRefresh} disabled={loading}><RefreshCw size={17} />重新检查</button>
      </div>
      <div className="admin-devices-layout">
        <div className="admin-device-column">
          <section className="admin-network-controls">
            <header><Signal size={20} /><div><h3>物理网络</h3><p>真实控制主机 Wi-Fi 与 QSM 数据网络</p></div></header>
            <div className="admin-network-control-grid">
              <article>
                <span className="admin-network-icon"><Wifi size={21} /></span>
                <div><strong>Wi-Fi</strong><small>{networkSettings?.wifi_ssid || (network.wifi_connected ? "已连接" : "未连接")}</small></div>
                <NetworkSwitch checked={Boolean(networkSettings?.wifi_enabled)} busy={!networkSettings || networkBusy === "wifi_enabled"} label="真实切换 Wi-Fi" onChange={(enabled) => updatePhysicalNetwork("wifi_enabled", enabled)} />
              </article>
              <article>
                <span className="admin-network-icon"><Signal size={21} /></span>
                <div><strong>数据网络</strong><small>{networkSettings?.sim_connected ? networkSettings.sim_operator || "已连接" : network.sim_present ? "已检测 SIM" : "未连接"}</small></div>
                <NetworkSwitch checked={Boolean(networkSettings?.sim_enabled)} busy={!networkSettings || networkBusy === "sim_enabled"} label="真实切换数据网络" onChange={(enabled) => updatePhysicalNetwork("sim_enabled", enabled)} />
              </article>
            </div>
          </section>
          <section className="admin-device-status-panel">
            <header><ServerCog size={20} /><h3>外设检查</h3><span>{overview?.generated_at || ""}</span></header>
            <div className="admin-device-table">
              {rows.map(([label, value]) => (
                <div key={label}><span className={`admin-status-dot ${value?.ok ? "ok" : "warn"}`} /><strong>{label}</strong><span>{deviceLabel(value)}</span><code>{value?.status || (value?.ok ? "ready" : "unavailable")}</code></div>
              ))}
            </div>
          </section>
        </div>
        <div className="admin-device-side-column">
          <section className="admin-pairing-panel">
            <header><KeyRound size={20} /><div><h3>家属配对</h3><p>选择服务对象后生成一次性配对码</p></div></header>
            <div className="admin-pairing-controls">
              <label>
                <UserRound size={17} aria-hidden="true" />
                <select value={pairingUserId} disabled={pairingBusy} onChange={(event) => { setPairingUserId(event.target.value); setIssuedPairing(null); }} aria-label="选择家属可查看的服务对象">
                  {pairingUsers.length === 0 && <option value="">暂无可配对对象</option>}
                  {pairingUsers.map((user) => <option key={user.id} value={user.id}>{user.name}</option>)}
                </select>
              </label>
              <button type="button" className="admin-button primary compact" onClick={issuePairingCode} disabled={pairingBusy || !pairingUserId}>
                {pairingBusy ? <LoaderCircle className="admin-spin" size={16} /> : <KeyRound size={16} />}
                {pairingBusy ? "生成中" : "生成配对码"}
              </button>
            </div>
            {issuedPairing ? (
              <div className="admin-pairing-code" role="status" aria-live="polite">
                <code>{issuedPairing.pairing_code}</code>
                <span><Timer size={15} />剩余 {countdownLabel(pairingRemaining)}</span>
                <small>授权对象：{issuedPairingScope || "待核对"} · 请让家属现在输入；过期后需重新生成</small>
              </div>
            ) : (
              <div className="admin-pairing-empty"><KeyRound size={21} /><span>配对码只会在这里显示一次</span></div>
            )}
          </section>
          <section className="admin-system-actions">
            <header><ShieldAlert size={20} /><div><h3>系统操作</h3><p>每次执行都需要二次确认并写入审计日志</p></div></header>
            <div>
              {actions.map(({ icon: Icon, ...action }) => (
                <button key={action.id} type="button" className={`admin-system-action ${action.tone}`} onClick={() => setPending(action)}>
                  <span><Icon size={21} /></span><div><strong>{action.title}</strong><small>{action.description}</small></div>
                </button>
              ))}
            </div>
          </section>
        </div>
      </div>
      <AdminConfirmDialog open={Boolean(pending)} title={pending?.title} description={pending?.description} expected={pending?.expected || ""} confirmLabel="确认执行" tone={pending?.tone} busy={busy} onCancel={() => setPending(null)} onConfirm={execute} />
    </div>
  );
}
