import { AlertTriangle, Bot, CheckCircle2, HeartPulse, Mic, Send, Speaker, UserRound } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { api, formBody } from "../api/client.js";
import { GlassCard } from "../components/GlassCard.jsx";
import { MarkdownText } from "../components/MarkdownText.jsx";
import { useAsyncAction } from "../hooks/useAsyncAction.js";

const safetyNotice = "本系统仅提供应急辅助信息和药品匹配参考，不能替代医生诊断、处方或专业救援判断。如出现严重症状，请立即联系医生、管理员或救援人员。";

const sceneOptions = [
  ["village", "村镇"],
  ["home", "家庭"],
  ["plateau", "高原"],
  ["scenic_spot", "景区"],
  ["enterprise", "园区"],
  ["construction_site", "工地"],
  ["school", "学校"],
  ["rescue_camp", "救援点"]
];

const quickPrompts = ["轻微头痛流涕", "腹泻一天", "皮肤瘙痒疑似过敏", "摔伤擦破皮", "老人头晕需复核降压药"];

export function AiChatPage({ status, site, profile, vitals, medicines, refresh, notify }) {
  const [messages, setMessages] = useState([
    { role: "assistant", text: "这里是 AI 应急问询。请描述症状、持续时间、已用药和过敏禁忌。系统只做风险提示和药品辅助匹配，不诊断、不开药、不生成处方。" }
  ]);
  const [symptoms, setSymptoms] = useState("");
  const [duration, setDuration] = useState("");
  const [usedMedicine, setUsedMedicine] = useState("");
  const [allergy, setAllergy] = useState(profile?.allergies || "");
  const [scene, setScene] = useState(site?.station_type || "village");
  const [result, setResult] = useState(null);
  const [lastReply, setLastReply] = useState("");
  const boxRef = useRef(null);
  const qsmOnline = Boolean(status?.qsm?.online);
  const network = status?.network || {};
  const currentVitals = vitals[0] || {};
  const stockedMeds = medicines.filter((item) => Number(item.stock) > 0);

  useEffect(() => {
    setAllergy(profile?.allergies || "");
  }, [profile?.allergies]);

  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [messages]);

  const [readVitals, readingVitals] = useAsyncAction(async () => {
    try {
      const data = await api("/api/vitals/read_all", { method: "POST" });
      notify(`体征已读取：体温 ${data.vitals?.temperature || "--"}`);
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  });

  const [listen, listening] = useAsyncAction(async () => {
    try {
      const data = await api("/api/audio/asr", formBody({ duration: 4 }));
      const text = data.text || data.transcript || data.asr?.text || data.result?.text || "";
      if (!text) throw new Error(data.detail || "没有识别到清晰语音");
      setSymptoms(text);
      notify("语音已转写到症状输入");
    } catch (err) {
      notify(err.message);
    }
  });

  const [triage, triaging] = useAsyncAction(async (text = symptoms.trim()) => {
    if (!text) return notify("请先输入症状或问询内容");
    const inquiryText = [
      `症状：${text}`,
      duration ? `持续时间：${duration}` : "",
      usedMedicine ? `已用药情况：${usedMedicine}` : "",
      allergy ? `过敏/禁忌：${allergy}` : ""
    ].filter(Boolean).join("；");
    setResult(null);
    setLastReply("");
    setMessages((current) => [...current, { role: "user", text: inquiryText }, { role: "assistant", text: "" }]);
    try {
      const payload = {
        symptoms_text: inquiryText,
        scene_type: scene,
        network_mode: network.mode || site?.network_mode || "weak",
        allergy_or_contraindication: allergy,
        vitals_snapshot: JSON.stringify(currentVitals),
        current_medicine_context: JSON.stringify(stockedMeds.slice(0, 8))
      };
      const res = await fetch("/api/ai/triage/stream", formBody(payload));
      if (!res.ok || !res.body) throw new Error("AI 应急问询连接失败");
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
          const line = part.split("\n").find((item) => item.startsWith("data:"));
          if (!line) continue;
          const data = JSON.parse(line.slice(5));
          if (data.delta) {
            reply += data.delta;
            setLastReply(reply);
            setMessages((current) => current.map((message, idx) => (idx === current.length - 1 ? { ...message, text: reply } : message)));
          }
          if (data.result) {
            setResult({ ...data.result, session_id: data.session_id });
          }
        }
      }
      await refresh();
    } catch (err) {
      notify(err.message);
      setMessages((current) => current.map((message, idx) => (idx === current.length - 1 ? { ...message, text: "应急问询暂不可用，已建议联系管理员人工复核。" } : message)));
    }
  });

  const [speakLast, speaking] = useAsyncAction(async () => {
    try {
      await api("/api/audio/speak", formBody({ text: lastReply || messages[messages.length - 1]?.text || safetyNotice }));
      notify("已发送到外设采集与执行控制平台播报");
    } catch (err) {
      notify(err.message);
    }
  });

  const [confirmDispense, confirmingDispense] = useAsyncAction(async () => {
    const candidate = result?.candidate_medicines?.[0];
    if (!candidate) return notify("当前没有可进入取药确认的库存药品");
    if (!result?.allow_self_confirm) return notify("当前风险等级需要管理员复核");
    try {
      const data = await api("/api/dispense", formBody({
        slot: candidate.slot,
        session_id: result.session_id || "",
        confirmed_by_user: 1,
        reason: "低风险应急问询取药确认"
      }));
      notify(data.dry_run ? "dry-run 已记录，未触发真实开仓" : data.detail);
      await refresh();
    } catch (err) {
      notify(err.message);
    }
  });

  return (
    <div className="ai-page triage-page">
      <GlassCard className="history-panel triage-input-panel">
        <span className="card-eyebrow">症状与场景</span>
        <label>
          症状输入
          <textarea value={symptoms} onChange={(event) => setSymptoms(event.target.value)} placeholder="例如：老人轻微咽痛流涕，无发热，想确认服务点是否有可用药品..." />
        </label>
        <label>
          持续时间
          <input value={duration} onChange={(event) => setDuration(event.target.value)} placeholder="例如：2小时、1天、3天反复出现" />
        </label>
        <label>
          已用药情况
          <input value={usedMedicine} onChange={(event) => setUsedMedicine(event.target.value)} placeholder="例如：未用药、已服降压药、刚吃退烧药" />
        </label>
        <label>
          过敏 / 禁忌
          <textarea value={allergy} onChange={(event) => setAllergy(event.target.value)} placeholder="例如：青霉素过敏、胃溃疡、正在服用降压药" />
        </label>
        <div className="scene-tags">
          {sceneOptions.map(([id, label]) => (
            <button key={id} className={scene === id ? "active" : ""} onClick={() => setScene(id)}>{label}</button>
          ))}
        </div>
        <div className="triage-tools">
          <button onClick={listen} disabled={!qsmOnline || listening}>
            <Mic size={18} />
            {listening ? "录音中" : "语音输入"}
          </button>
          <button onClick={readVitals} disabled={!qsmOnline || readingVitals}>
            <HeartPulse size={18} />
            {readingVitals ? "读取中" : "读取体征"}
          </button>
          <button className="primary" onClick={() => triage()} disabled={!symptoms.trim() || triaging}>
            <Send size={18} />
            {triaging ? "评估中" : "开始问询"}
          </button>
        </div>
        <div className="quick-prompts">
          {quickPrompts.map((prompt) => (
            <button key={prompt} onClick={() => triage(prompt)} disabled={triaging}>{prompt}</button>
          ))}
        </div>
      </GlassCard>

      <GlassCard className="chat-panel">
        <div className="chat-heading">
          <Bot size={28} />
          <div>
            <span className="card-eyebrow">问询 → 风险判断 → 库存匹配 → 复核</span>
            <h1>风险提示与药品辅助匹配</h1>
          </div>
          <button onClick={speakLast} disabled={!qsmOnline || speaking}>
            <Speaker size={18} />
            播报
          </button>
        </div>
        <div className="safety-banner">
          <AlertTriangle size={18} />
          <span>{safetyNotice}</span>
        </div>
        <div className="chat-feed" ref={boxRef}>
          {messages.map((message, idx) => (
            <article key={`${message.role}-${idx}`} className={`chat-message ${message.role}`}>
              <div className="avatar">{message.role === "assistant" ? <Bot size={22} /> : <UserRound size={22} />}</div>
              <div className="bubble">
                <MarkdownText text={message.text} />
              </div>
            </article>
          ))}
        </div>
        <div className="composer">
          <textarea value={symptoms} onChange={(event) => setSymptoms(event.target.value)} placeholder="输入应急问询内容..." aria-label="输入应急问询内容" />
          <button className="primary" onClick={() => triage()} disabled={!symptoms.trim() || triaging} aria-busy={triaging || undefined}>
            <Send size={24} />
          </button>
        </div>
      </GlassCard>

      <GlassCard className="health-context-panel triage-result-panel">
        <span className="card-eyebrow">风险等级</span>
        <div className={`risk-badge ${result?.risk_level || "unknown"}`}>{riskLabel(result?.risk_level)}</div>
        <span className="card-eyebrow">症状摘要</span>
        <div className="result-summary-box">
          {result?.symptoms_summary || "完成问询后显示症状摘要、场景和需要复核的关键点。"}
        </div>
        <span className="card-eyebrow">当前库存匹配</span>
        <div className="med-context-list">
          {(result?.candidate_medicines || []).length ? result.candidate_medicines.map((item) => (
            <p key={`${item.slot}-${item.name}`}>
              <strong>{item.name || `${item.slot} 号仓`}</strong>
              <span>{item.category || "应急药品"} · 余 {item.stock}{item.unit || "件"}</span>
            </p>
          )) : <p className="muted">问询后显示候选药品。当前库存 {stockedMeds.length}/23 仓。</p>}
        </div>
        <span className="card-eyebrow">候选药品类别</span>
        <div className="token-row">
          {(result?.suggested_categories || ["待评估"]).map((item) => <span key={item}>{item}</span>)}
        </div>
        <span className="card-eyebrow">禁忌提醒</span>
        <div className="warning-list">
          {(result?.safety_warnings || ["请核对说明书、过敏史、基础疾病和重复用药风险。"]).map((item) => <p key={item}>{item}</p>)}
        </div>
        <span className="card-eyebrow">后续动作</span>
        <div className="condition-list">
          <p><strong>取药确认</strong><span>{result?.allow_self_confirm ? "低风险可自助确认" : "需要管理员复核"}</span></p>
          <p><strong>AI 模式</strong><span>{result?.ai_mode || aiModeLabel(network.ai_mode)}</span></p>
          <p><strong>体征</strong><span>心率 {currentVitals.heart_rate || "--"} · 血氧 {currentVitals.spo2 || "--"}</span></p>
        </div>
        <button className="primary wide" onClick={confirmDispense} disabled={!result?.allow_self_confirm || confirmingDispense}>
          <CheckCircle2 size={20} />
          {confirmingDispense ? "记录中" : "进入取药确认"}
        </button>
        <span className="qsm-note">中/高/紧急风险必须联系管理员、医生或救援人员。</span>
      </GlassCard>
    </div>
  );
}

function modeLabel(mode) {
  return { online: "在线", weak: "弱网", offline: "离线" }[mode] || "弱网";
}

function aiModeLabel(mode) {
  return { cloud: "云端AI", local: "本地AI", rules: "规则兜底" }[mode] || "本地AI";
}

function riskLabel(value) {
  return { low: "低风险", medium: "中风险", high: "高风险", emergency: "紧急风险" }[value] || "待评估";
}
