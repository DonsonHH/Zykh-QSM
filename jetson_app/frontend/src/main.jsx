import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Bot,
  Boxes,
  Camera,
  ChevronRight,
  CircleGauge,
  HeartPulse,
  Home,
  Mic,
  Pill,
  Radio,
  RefreshCw,
  Send,
  Settings,
  Speaker,
  WifiOff
} from "lucide-react";
import "./styles.css";

const API = "";

async function api(path, options = {}) {
  const res = await fetch(`${API}${path}`, options);
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || data.detail || "请求失败");
  return data;
}

function formBody(data) {
  return {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(data).toString()
  };
}

function App() {
  const [page, setPage] = useState("home");
  const [status, setStatus] = useState(null);
  const [medicines, setMedicines] = useState([]);
  const [plans, setPlans] = useState([]);
  const [records, setRecords] = useState([]);
  const [vitals, setVitals] = useState([]);
  const [profile, setProfile] = useState({});
  const [toast, setToast] = useState("");

  const notify = (message) => {
    setToast(message);
    window.clearTimeout(notify.timer);
    notify.timer = window.setTimeout(() => setToast(""), 2600);
  };

  const refresh = async () => {
    const [statusRes, medRes, planRes, recordRes, vitalRes, profileRes] = await Promise.all([
      api("/api/status"),
      api("/api/medicines"),
      api("/api/plans"),
      api("/api/records"),
      api("/api/vitals"),
      api("/api/profile")
    ]);
    setStatus(statusRes);
    setMedicines(medRes.medicines || []);
    setPlans(planRes.plans || []);
    setRecords(recordRes.records || []);
    setVitals(vitalRes.vitals || []);
    setProfile(profileRes.profile || {});
  };

  useEffect(() => {
    refresh().catch((err) => notify(err.message));
    const timer = window.setInterval(() => refresh().catch(() => {}), 15000);
    return () => window.clearInterval(timer);
  }, []);

  const common = { status, medicines, plans, records, vitals, profile, refresh, notify, setPage };

  return (
    <main className="app-shell">
      <Sidebar page={page} setPage={setPage} status={status} />
      <section className="screen">
        <Topbar status={status} profile={profile} />
        {page === "home" && <HomePage {...common} />}
        {page === "cabinet" && <CabinetPage {...common} />}
        {page === "camera" && <CameraPage {...common} />}
        {page === "consult" && <ConsultPage {...common} />}
        {page === "admin" && <AdminPage {...common} />}
      </section>
      <div className={`toast ${toast ? "show" : ""}`}>{toast}</div>
    </main>
  );
}

function Sidebar({ page, setPage, status }) {
  const nav = [
    ["home", Home, "首页"],
    ["cabinet", Boxes, "药柜"],
    ["camera", Camera, "识药"],
    ["consult", Bot, "问诊"],
    ["admin", Settings, "管理"]
  ];
  const online = status?.qsm?.online;
  return (
    <aside className="sidebar">
      <div className="logo">
        <span>AI</span>
        <strong>智药康护</strong>
        <small>Jetson Master</small>
      </div>
      <nav>
        {nav.map(([id, Icon, label]) => (
          <button key={id} className={page === id ? "active" : ""} onClick={() => setPage(id)}>
            <Icon size={24} />
            <span>{label}</span>
          </button>
        ))}
      </nav>
      <div className={`link-status ${online ? "online" : "offline"}`}>
        {online ? <Radio size={22} /> : <WifiOff size={22} />}
        <div>
          <strong>{online ? "QSM 在线" : "QSM 离线"}</strong>
          <small>{online ? "外设网关可用" : "仅本地数据可用"}</small>
        </div>
      </div>
    </aside>
  );
}

function Topbar({ status, profile }) {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <header className="topbar">
      <div>
        <span className="eyebrow">家庭智慧康护中枢</span>
        <h1>{profile?.name ? `${profile.name} 的康护终端` : "智药康护 Jetson 主控"}</h1>
      </div>
      <div className="top-status">
        <span>{status?.jetson?.host || "Jetson"}</span>
        <strong>{now.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</strong>
        <small>{now.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" })}</small>
      </div>
    </header>
  );
}

function HomePage({ status, medicines, plans, records, vitals, refresh, notify, setPage }) {
  const nextPlan = plans.find((plan) => plan.enabled) || null;
  const latestVitals = vitals[0] || {};
  const low = medicines.filter((m) => Number(m.stock) > 0 && Number(m.stock) <= 10).length;
  const filled = medicines.filter((m) => Number(m.stock) > 0).length;

  const dispense = async () => {
    if (!nextPlan) return notify("当前没有可执行用药计划");
    try {
      const data = await api("/api/dispense", formBody({ slot: nextPlan.slot }));
      notify(data.detail || "取药完成");
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  };

  const readVitals = async () => {
    try {
      const data = await api("/api/vitals/read_all", { method: "POST" });
      notify(`体征已写入：心率 ${data.vitals?.heart_rate || "--"} / 血氧 ${data.vitals?.spo2 || "--"}`);
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  };

  return (
    <div className="home-grid">
      <section className="hero-panel">
        <div className="system-mark">
          <CircleGauge size={74} />
          <span>Jetson</span>
        </div>
        <div>
          <span className="eyebrow">下一次服药</span>
          <h2>{nextPlan ? nextPlan.medicine_name || `${nextPlan.slot} 号仓` : "暂无用药计划"}</h2>
          <p>{nextPlan ? `${nextPlan.time} · ${nextPlan.amount} · ${nextPlan.slot} 号仓` : "进入药柜或管理页添加计划"}</p>
        </div>
        <button className="primary-action" onClick={dispense} disabled={!status?.qsm?.online || !nextPlan}>
          <Pill size={34} />
          <span>开始取药</span>
        </button>
      </section>

      <ActionCard icon={HeartPulse} title="测量体征" detail={`体温 ${latestVitals.temperature || "--"}℃ · 心率 ${latestVitals.heart_rate || "--"} · 血氧 ${latestVitals.spo2 || "--"}%`} onClick={readVitals} disabled={!status?.qsm?.online} />
      <ActionCard icon={Camera} title="拍照识药" detail="实时预览、条码识别、有效期确认" onClick={() => setPage("camera")} />
      <ActionCard icon={Bot} title="AI 问诊" detail="结合档案、体征、病例记忆和药柜库存" onClick={() => setPage("consult")} />

      <section className="status-matrix">
        <Metric label="QSM 网关" value={status?.qsm?.online ? "在线" : "离线"} tone={status?.qsm?.online ? "good" : "bad"} />
        <Metric label="药柜占用" value={`${filled}/23`} tone="info" />
        <Metric label="低库存" value={`${low}`} tone={low ? "warn" : "good"} />
        <Metric label="今日记录" value={`${records.length}`} tone="info" />
      </section>

      <section className="cabinet-strip">
        <div className="section-head">
          <div>
            <span className="eyebrow">23 仓药柜</span>
            <h2>库存态势</h2>
          </div>
          <button onClick={() => setPage("cabinet")}>查看全部 <ChevronRight size={18} /></button>
        </div>
        <div className="mini-slots">
          {medicines.slice(0, 12).map((med) => (
            <span key={med.slot} className={Number(med.stock) <= 0 ? "empty" : Number(med.stock) <= 10 ? "low" : "full"}>
              {String(med.slot).padStart(2, "0")}
            </span>
          ))}
        </div>
      </section>
    </div>
  );
}

function ActionCard({ icon: Icon, title, detail, onClick, disabled }) {
  return (
    <button className="action-card" onClick={onClick} disabled={disabled}>
      <Icon size={36} />
      <strong>{title}</strong>
      <span>{detail}</span>
    </button>
  );
}

function Metric({ label, value, tone }) {
  return (
    <div className={`metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

const cabinetLayout = [
  ...Array.from({ length: 8 }, (_, i) => ({ slot: i + 1, kind: "big" })),
  ...Array.from({ length: 9 }, (_, i) => ({ slot: i + 9, kind: "small" })),
  ...Array.from({ length: 6 }, (_, i) => ({ slot: i + 18, kind: "medium" }))
];

function CabinetPage({ status, medicines, refresh, notify }) {
  const [selected, setSelected] = useState(1);
  const med = medicines.find((item) => Number(item.slot) === selected) || {};
  const [draft, setDraft] = useState({});
  const [planDraft, setPlanDraft] = useState({ time: "08:00", amount: "1片" });

  useEffect(() => setDraft(med), [selected, medicines]);

  const save = async () => {
    try {
      await api("/api/medicines", formBody({ ...draft, slot: selected }));
      notify(`${selected} 号仓已保存`);
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  };
  const open = async () => {
    try {
      const data = await api("/api/dispense", formBody({ slot: selected }));
      notify(data.detail || "开仓完成");
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  };
  const addPlan = async () => {
    try {
      await api("/api/plans", formBody({ slot: selected, time: planDraft.time, amount: planDraft.amount, enabled: 1 }));
      notify(`${selected} 号仓用药计划已添加`);
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  };

  return (
    <div className="cabinet-layout">
      <section className="cabinet-map">
        {cabinetLayout.map((item) => {
          const m = medicines.find((x) => Number(x.slot) === item.slot);
          const stock = Number(m?.stock || 0);
          return (
            <button key={item.slot} className={`cab-slot ${item.kind} ${selected === item.slot ? "selected" : ""} ${stock <= 0 ? "empty" : stock <= 10 ? "low" : "full"}`} onClick={() => setSelected(item.slot)}>
              <strong>{String(item.slot).padStart(2, "0")}</strong>
              <span>{item.kind === "big" ? "大仓" : item.kind === "small" ? "小仓" : "中仓"}</span>
              <em>{stock > 0 ? `${stock}` : "空"}</em>
            </button>
          );
        })}
      </section>
      <aside className="edit-panel">
        <span className="eyebrow">仓位详情</span>
        <h2>{selected} 号仓</h2>
        <label>药品名称<input value={draft.name || ""} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
        <label>规格剂量<input value={draft.dosage || ""} onChange={(e) => setDraft({ ...draft, dosage: e.target.value })} /></label>
        <label>库存数量<input type="number" value={draft.stock || 0} onChange={(e) => setDraft({ ...draft, stock: e.target.value })} /></label>
        <label>有效期<input value={draft.expire_date || ""} onChange={(e) => setDraft({ ...draft, expire_date: e.target.value })} /></label>
        <div className="panel-actions">
          <button className="primary" onClick={save}>保存</button>
          <button onClick={open} disabled={!status?.qsm?.online}>开仓</button>
        </div>
        <div className="plan-box">
          <span className="eyebrow">用药计划</span>
          <label>时间<input value={planDraft.time} onChange={(e) => setPlanDraft({ ...planDraft, time: e.target.value })} /></label>
          <label>剂量<input value={planDraft.amount} onChange={(e) => setPlanDraft({ ...planDraft, amount: e.target.value })} /></label>
          <button className="wide" onClick={addPlan}>添加计划</button>
        </div>
      </aside>
    </div>
  );
}

function CameraPage({ status, refresh, notify }) {
  const [live, setLive] = useState(true);
  const [result, setResult] = useState(null);
  const [draft, setDraft] = useState({ slot: 1, stock: 1, expire_date: "" });
  const [streamKey, setStreamKey] = useState(Date.now());
  const streamUrl = useMemo(() => `/api/camera/stream?width=640&height=480&fps=24&t=${streamKey}`, [streamKey]);

  const scan = async () => {
    setLive(false);
    try {
      const data = await api("/api/medicine/scan", { method: "POST" });
      setResult(data);
      const medicine = data.scan?.medicine || data.scan?.lookup?.medicine || data.scan?.result || {};
      setDraft({
        slot: data.suggestion?.slot || 1,
        stock: data.suggestion?.stock || 1,
        expire_date: medicine.expire_date || medicine.expiry_date || "",
        dosage: medicine.dosage || medicine.spec || "",
        code: data.scan?.code || medicine.code || "",
        trace_code: medicine.trace_code || "",
        box_size: data.suggestion?.box_size || "medium",
        name: medicine.name || medicine.medicine_name || ""
      });
      notify("识别完成，请核对后录入");
    } catch (err) {
      notify(err.message);
      setLive(true);
      setStreamKey(Date.now());
    }
  };
  const confirm = async () => {
    try {
      await api("/api/medicine/scan", formBody({ ...draft, confirm: 1 }));
      notify(`${draft.slot} 号仓已录入`);
      await refresh();
      setLive(true);
      setStreamKey(Date.now());
    } catch (err) {
      notify(err.message);
    }
  };

  return (
    <div className="camera-layout">
      <section className="camera-stage">
        {status?.qsm?.online && live ? <img src={streamUrl} alt="QSM camera stream" /> : <div className="camera-placeholder"><Camera size={80} /><span>{status?.qsm?.online ? "预览已暂停" : "QSM 离线"}</span></div>}
        <div className="scan-frame"></div>
      </section>
      <aside className="scan-panel">
        <span className="eyebrow">药品识别</span>
        <h2>条码 / 药盒 / 有效期</h2>
        <p>{result ? result.scan?.detail || "请核对识别结果，再写入 Jetson 主库。" : "将药盒放入框内，点击拍照识别。"}</p>
        <div className="panel-actions">
          <button className="primary" onClick={scan} disabled={!status?.qsm?.online}>拍照识别</button>
          <button onClick={() => { setLive(!live); setStreamKey(Date.now()); }}>{live ? "暂停" : "继续"}</button>
        </div>
        <label>药品名称<input value={draft.name || ""} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
        <label>规格剂量<input value={draft.dosage || ""} onChange={(e) => setDraft({ ...draft, dosage: e.target.value })} /></label>
        <label>仓位<input type="number" min="1" max="23" value={draft.slot} onChange={(e) => setDraft({ ...draft, slot: e.target.value })} /></label>
        <label>数量<input type="number" value={draft.stock} onChange={(e) => setDraft({ ...draft, stock: e.target.value })} /></label>
        <label>有效期<input value={draft.expire_date || ""} onChange={(e) => setDraft({ ...draft, expire_date: e.target.value })} /></label>
        <button className="primary wide" onClick={confirm}>确认录入</button>
      </aside>
    </div>
  );
}

function ConsultPage({ status, profile, vitals, medicines, notify }) {
  const [messages, setMessages] = useState([{ role: "assistant", text: "您好，我是智药康护 AI 助手。可以结合档案、体征和药柜库存，为您做健康咨询和用药提醒。" }]);
  const [input, setInput] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const [listening, setListening] = useState(false);
  const boxRef = useRef(null);

  const send = async (text = input.trim()) => {
    if (!text) return;
    setInput("");
    const next = [...messages, { role: "user", text }, { role: "assistant", text: "" }];
    setMessages(next);
    try {
      const res = await fetch("/api/ai/chat/stream", formBody({ message: text }));
      if (!res.ok || !res.body) throw new Error("AI 问诊连接失败");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let reply = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";
        for (const part of parts) {
          const line = part.split("\n").find((x) => x.startsWith("data:"));
          if (!line) continue;
          const data = JSON.parse(line.slice(5));
          if (data.delta) {
            reply += data.delta;
            setMessages((current) => current.map((m, idx) => (idx === current.length - 1 ? { ...m, text: reply } : m)));
          }
        }
      }
    } catch (err) {
      notify(err.message);
      setMessages((current) => current.map((m, idx) => (idx === current.length - 1 ? { ...m, text: "AI 问诊暂时不可用，请稍后重试。" } : m)));
    }
  };

  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [messages]);

  const speakLast = async () => {
    const last = [...messages].reverse().find((m) => m.role === "assistant" && m.text)?.text || "";
    setSpeaking(true);
    try {
      await api("/api/audio/speak", formBody({ text: last }));
      notify("已发送到 QSM 喇叭播报");
    } catch (err) {
      notify(err.message);
    } finally {
      setSpeaking(false);
    }
  };

  const listen = async () => {
    setListening(true);
    try {
      const data = await api("/api/audio/asr", formBody({ duration: 4 }));
      const text = data.text || data.transcript || data.asr?.text || data.result?.text || "";
      if (!text) throw new Error(data.detail || "没有识别到语音");
      setInput(text);
      notify("语音已转写");
    } catch (err) {
      notify(err.message);
    } finally {
      setListening(false);
    }
  };

  return (
    <div className="consult-layout">
      <aside className="context-card">
        <span className="eyebrow">上下文</span>
        <h2>{profile.name || "未填写姓名"}</h2>
        <p>{profile.conditions || "暂无慢病记录"}</p>
        <Metric label="最近体温" value={`${vitals[0]?.temperature || "--"}℃`} tone="info" />
        <Metric label="最近心率" value={`${vitals[0]?.heart_rate || "--"}`} tone="info" />
        <Metric label="药柜药品" value={`${medicines.filter((m) => Number(m.stock) > 0).length}`} tone="good" />
      </aside>
      <section className="chat-card">
        <div className="chat-feed" ref={boxRef}>
          {messages.map((msg, idx) => <article key={idx} className={`chat-msg ${msg.role}`}>{renderMarkdown(msg.text)}</article>)}
        </div>
        <div className="composer">
          <button onClick={listen} disabled={!status?.qsm?.online || listening}><Mic size={24} /></button>
          <textarea value={input} onChange={(e) => setInput(e.target.value)} placeholder="输入健康问题，例如：今天血压偏高怎么办？" />
          <button className="primary" onClick={() => send()}><Send size={24} /></button>
          <button onClick={speakLast} disabled={!status?.qsm?.online || speaking}><Speaker size={24} /></button>
        </div>
      </section>
      <aside className="quick-card">
        {["今天该吃哪些药？", "血氧低要注意什么？", "头晕怎么办？", "药品有副作用吗？"].map((q) => <button key={q} onClick={() => send(q)}>{q}</button>)}
      </aside>
    </div>
  );
}

function AdminPage({ status, profile, records, refresh, notify }) {
  const [draft, setDraft] = useState(profile || {});
  const [settings, setSettings] = useState(null);
  const [apiKey, setApiKey] = useState("");
  useEffect(() => setDraft(profile || {}), [profile]);
  useEffect(() => {
    api("/api/settings").then((data) => setSettings(data.settings)).catch(() => {});
  }, []);
  const save = async () => {
    try {
      await api("/api/profile", formBody(draft));
      notify("档案已保存");
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  };
  const saveKey = async () => {
    try {
      const data = await api("/api/settings/ai_key", formBody({ api_key: apiKey }));
      setSettings(data.settings);
      notify(apiKey ? "AI Key 已保存到 Jetson 本地" : "AI Key 已清除");
      setApiKey("");
    } catch (err) {
      notify(err.message);
    }
  };
  const resetDb = async () => {
    const confirm = window.prompt("输入 RESET 重新初始化 Jetson 主库");
    if (confirm !== "RESET") return;
    try {
      await api("/api/admin/reset", formBody({ confirm }));
      notify("Jetson 主库已重新初始化");
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  };
  return (
    <div className="admin-grid">
      <section className="admin-panel">
        <span className="eyebrow">系统</span>
        <h2>QSM 网关</h2>
        <pre>{JSON.stringify(status?.qsm || {}, null, 2)}</pre>
        <button onClick={refresh}><RefreshCw size={18} /> 刷新状态</button>
      </section>
      <section className="admin-panel">
        <span className="eyebrow">AI / 数据</span>
        <h2>本地配置</h2>
        <div className="settings-list">
          <p>模型：{settings?.ai_model || "--"}</p>
          <p>Key：{settings?.ai_key_configured ? "已配置" : "未配置"}</p>
          <p>主库：{settings?.db_path || "--"}</p>
        </div>
        <label>API Key<input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} /></label>
        <div className="panel-actions">
          <button className="primary" onClick={saveKey}>保存 Key</button>
          <button onClick={resetDb}>初始化主库</button>
        </div>
        <span className="eyebrow admin-subhead">最近记录</span>
        <div className="record-list">
          {records.slice(0, 6).map((record) => (
            <p key={record.id}>{record.created_at} · {record.action} · {record.result}</p>
          ))}
        </div>
      </section>
      <section className="admin-panel">
        <span className="eyebrow">档案</span>
        <h2>老人基本信息</h2>
        <label>姓名<input value={draft.name || ""} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
        <label>年龄<input value={draft.age || ""} onChange={(e) => setDraft({ ...draft, age: e.target.value })} /></label>
        <label>慢病<textarea value={draft.conditions || ""} onChange={(e) => setDraft({ ...draft, conditions: e.target.value })} /></label>
        <label>过敏史<textarea value={draft.allergies || ""} onChange={(e) => setDraft({ ...draft, allergies: e.target.value })} /></label>
        <button className="primary" onClick={save}>保存档案</button>
      </section>
    </div>
  );
}

function renderMarkdown(text) {
  if (!text) return <p className="muted">正在生成...</p>;
  return text.split(/\n+/).map((line, idx) => {
    const clean = line.trim();
    if (!clean) return null;
    if (clean.startsWith("#")) return <strong key={idx}>{clean.replace(/^#+\s*/, "")}</strong>;
    if (/^[-*]\s+/.test(clean)) return <p key={idx}>• {clean.replace(/^[-*]\s+/, "")}</p>;
    const parts = clean.split(/(\*\*.*?\*\*)/g).filter(Boolean);
    return (
      <p key={idx}>
        {parts.map((part, i) => (part.startsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : part))}
      </p>
    );
  });
}

createRoot(document.getElementById("root")).render(<App />);
