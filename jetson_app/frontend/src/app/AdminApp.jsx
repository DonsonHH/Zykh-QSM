import React, { useEffect, useState } from "react";
import { Bot, Camera, Cpu, Database, DoorOpen, HeartPulse, Home, KeyRound, RefreshCw, Server, Settings, Shield, UserRound } from "lucide-react";
import { api, formBody } from "../api/client.js";
import { DeviceCard } from "../components/DeviceCard.jsx";
import { GlassCard } from "../components/GlassCard.jsx";
import { useJetsonData } from "./useJetsonData.js";

const adminNav = [
  ["overview", Home, "系统概览"],
  ["devices", Server, "设备管理"],
  ["medicines", Database, "药品管理"],
  ["profile", UserRound, "健康档案"],
  ["settings", Settings, "系统设置"],
  ["logs", Shield, "日志管理"]
];

export function AdminApp() {
  const data = useJetsonData();
  const [section, setSection] = useState("overview");
  const [settings, setSettings] = useState(null);
  const [apiKey, setApiKey] = useState("");
  const [slot, setSlot] = useState(1);
  const [profileDraft, setProfileDraft] = useState({});

  useEffect(() => setProfileDraft(data.profile || {}), [data.profile]);
  useEffect(() => {
    api("/api/settings").then((res) => setSettings(res.settings)).catch(() => {});
  }, []);

  const qsmOnline = Boolean(data.status?.qsm?.online);
  const forwardOk = Boolean(data.status?.qsm?.forward?.ok ?? data.status?.qsm?.forward);
  const qsmStatus = data.status?.qsm?.status || {};
  const latestVital = data.vitals[0] || {};

  const saveProfile = async () => {
    try {
      await api("/api/profile", formBody(profileDraft));
      data.notify("档案已保存");
      await data.refresh();
    } catch (err) {
      data.notify(err.message);
    }
  };

  const saveKey = async () => {
    try {
      const res = await api("/api/settings/ai_key", formBody({ api_key: apiKey }));
      setSettings(res.settings);
      setApiKey("");
      data.notify(apiKey ? "AI Key 已保存到 Jetson 本地" : "AI Key 已清除");
    } catch (err) {
      data.notify(err.message);
    }
  };

  const resetDb = async () => {
    const confirm = window.prompt("输入 RESET 重新初始化 Jetson 主库");
    if (confirm !== "RESET") return;
    try {
      await api("/api/admin/reset", formBody({ confirm }));
      data.notify("Jetson 主库已重新初始化");
      await data.refresh();
    } catch (err) {
      data.notify(err.message);
    }
  };

  const openSlot = async () => {
    const confirmed = window.confirm(`确认打开 ${slot} 号仓？\n此操作会触发 QSM UART8 开仓机构。`);
    if (!confirmed) return;
    try {
      const res = await api("/api/dispense", formBody({ slot }));
      data.notify(res.detail || `${slot} 号仓开仓完成`);
      await data.refresh();
    } catch (err) {
      data.notify(err.message);
    }
  };

  return (
    <main className="viewport admin-viewport">
      <section className="admin-shell">
        <aside className="admin-sidebar">
          <div className="admin-brand">
            <Shield size={30} />
            <div>
              <strong>系统管理后台</strong>
              <span>Jetson 控制台</span>
            </div>
          </div>
          <nav>
            {adminNav.map(([id, Icon, label]) => (
              <button key={id} className={section === id ? "active" : ""} onClick={() => setSection(id)}>
                <Icon size={20} />
                <span>{label}</span>
              </button>
            ))}
          </nav>
          <a className="terminal-link" href="/terminal">返回终端</a>
        </aside>

        <section className="admin-workspace">
          <header className="admin-header">
            <div>
              <span className="card-eyebrow">系统概览</span>
              <h1>{sectionTitle(section)}</h1>
            </div>
            <div className="admin-user">
              <UserRound size={24} />
              <span>管理员</span>
            </div>
          </header>

          {section === "overview" && (
            <div className="admin-overview">
              <div className="device-grid">
                <DeviceCard icon={Cpu} title="QSM 设备" value={qsmOnline ? "在线" : "离线"} detail={forwardOk ? "ADB 转发正常" : "请检查 ADB forward"} tone={qsmOnline ? "good" : "bad"} />
                <DeviceCard icon={Camera} title="摄像头" value={qsmOnline ? "正常" : "不可用"} detail={qsmStatus.camera || "经 QSM 网关访问"} tone={qsmOnline ? "good" : "warn"} />
                <DeviceCard icon={HeartPulse} title="心率血氧仪" value={latestVital.heart_rate ? "正常" : "待测量"} detail={`心率 ${latestVital.heart_rate || "--"} · 血氧 ${latestVital.spo2 || "--"}`} tone={latestVital.heart_rate ? "good" : "warn"} />
                <DeviceCard icon={DoorOpen} title="开仓控制" value={qsmOnline ? "正常" : "禁用"} detail={`累计记录 ${data.records.length} 次`} tone={qsmOnline ? "good" : "bad"} />
              </div>
              <GlassCard className="admin-stats">
                <Metric label="药柜库存仓" value={`${data.medicines.filter((item) => Number(item.stock) > 0).length}/23`} />
                <Metric label="用药计划" value={data.plans.length} />
                <Metric label="体征记录" value={data.vitals.length} />
                <Metric label="操作记录" value={data.records.length} />
              </GlassCard>
              <AdminLogs records={data.records} />
              <QuickActions qsmOnline={qsmOnline} slot={slot} setSlot={setSlot} openSlot={openSlot} refresh={data.refresh} resetDb={resetDb} />
            </div>
          )}

          {section === "devices" && (
            <div className="admin-two-col">
              <GlassCard className="admin-panel">
                <span className="card-eyebrow">QSM 原始状态</span>
                <pre>{JSON.stringify(data.status?.qsm || {}, null, 2)}</pre>
                <button onClick={data.refresh}>
                  <RefreshCw size={18} />
                  刷新状态
                </button>
              </GlassCard>
              <QuickActions qsmOnline={qsmOnline} slot={slot} setSlot={setSlot} openSlot={openSlot} refresh={data.refresh} resetDb={resetDb} />
            </div>
          )}

          {section === "medicines" && (
            <GlassCard className="admin-panel full">
              <span className="card-eyebrow">药品主数据</span>
              <div className="admin-table">
                {data.medicines.map((item) => (
                  <p key={item.slot}>
                    <strong>{String(item.slot).padStart(2, "0")}</strong>
                    <span>{item.name || "空仓"}</span>
                    <span>{item.dosage || "--"}</span>
                    <span>{item.stock || 0}</span>
                    <span>{item.expire_date || "--"}</span>
                  </p>
                ))}
              </div>
            </GlassCard>
          )}

          {section === "profile" && (
            <GlassCard className="admin-panel profile-editor-admin">
              <span className="card-eyebrow">老人基本信息</span>
              <div className="admin-form-grid">
                <label>姓名<input value={profileDraft.name || ""} onChange={(event) => setProfileDraft({ ...profileDraft, name: event.target.value })} /></label>
                <label>性别<input value={profileDraft.gender || ""} onChange={(event) => setProfileDraft({ ...profileDraft, gender: event.target.value })} /></label>
                <label>年龄<input value={profileDraft.age || ""} onChange={(event) => setProfileDraft({ ...profileDraft, age: event.target.value })} /></label>
                <label>身高<input value={profileDraft.height || ""} onChange={(event) => setProfileDraft({ ...profileDraft, height: event.target.value })} /></label>
                <label>体重<input value={profileDraft.weight || ""} onChange={(event) => setProfileDraft({ ...profileDraft, weight: event.target.value })} /></label>
                <label>慢病<textarea value={profileDraft.conditions || ""} onChange={(event) => setProfileDraft({ ...profileDraft, conditions: event.target.value })} /></label>
                <label>过敏史<textarea value={profileDraft.allergies || ""} onChange={(event) => setProfileDraft({ ...profileDraft, allergies: event.target.value })} /></label>
                <label>备注<textarea value={profileDraft.notes || ""} onChange={(event) => setProfileDraft({ ...profileDraft, notes: event.target.value })} /></label>
              </div>
              <button className="primary" onClick={saveProfile}>保存档案</button>
            </GlassCard>
          )}

          {section === "settings" && (
            <div className="admin-two-col">
              <GlassCard className="admin-panel">
                <span className="card-eyebrow">AI / 数据</span>
                <p>模型：{settings?.ai_model || "--"}</p>
                <p>Key：{settings?.ai_key_configured ? "已配置" : "未配置"}</p>
                <p>主库：{settings?.db_path || "--"}</p>
                <label>API Key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></label>
                <div className="admin-actions-row">
                  <button className="primary" onClick={saveKey}>
                    <KeyRound size={18} />
                    保存 Key
                  </button>
                  <button onClick={resetDb}>
                    <Database size={18} />
                    初始化主库
                  </button>
                </div>
              </GlassCard>
              <GlassCard className="admin-panel">
                <span className="card-eyebrow">Jetson 状态</span>
                <pre>{JSON.stringify(data.status?.jetson || {}, null, 2)}</pre>
              </GlassCard>
            </div>
          )}

          {section === "logs" && <AdminLogs records={data.records} large />}
        </section>
        <div className={`toast ${data.toast ? "show" : ""}`}>{data.toast}</div>
      </section>
    </main>
  );
}

function sectionTitle(section) {
  const item = adminNav.find(([id]) => id === section);
  return item ? item[2] : "系统概览";
}

function Metric({ label, value }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function AdminLogs({ records, large = false }) {
  return (
    <GlassCard className={`admin-logs ${large ? "large" : ""}`}>
      <div className="panel-title">
        <span className="card-eyebrow">系统日志</span>
        <a href="/terminal">查看终端</a>
      </div>
      <div className="log-list">
        {records.slice(0, large ? 14 : 5).map((record) => (
          <p key={record.id}>
            <span>{record.created_at}</span>
            <strong>{record.action}</strong>
            <em>{record.result}</em>
          </p>
        ))}
        {!records.length && <p className="muted">暂无日志</p>}
      </div>
    </GlassCard>
  );
}

function QuickActions({ qsmOnline, slot, setSlot, openSlot, refresh, resetDb }) {
  return (
    <GlassCard className="quick-actions-panel">
      <span className="card-eyebrow">快捷操作</span>
      <div className="slot-test-row">
        <label>
          开仓仓位
          <input type="number" min="1" max="23" value={slot} onChange={(event) => setSlot(event.target.value)} />
        </label>
        <button onClick={openSlot} disabled={!qsmOnline}>
          <DoorOpen size={18} />
          测试开仓
        </button>
      </div>
      <button onClick={refresh}>
        <RefreshCw size={18} />
        刷新状态
      </button>
      <button onClick={resetDb}>
        <Database size={18} />
        初始化主库
      </button>
      <a href="/terminal">
        <Bot size={18} />
        打开老人终端
      </a>
    </GlassCard>
  );
}
