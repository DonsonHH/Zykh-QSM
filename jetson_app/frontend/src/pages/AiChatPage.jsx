import { Bot, Mic, Plus, Send, Speaker, UserRound } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { api, formBody } from "../api/client.js";
import { GlassCard } from "../components/GlassCard.jsx";
import { MarkdownText } from "../components/MarkdownText.jsx";
import { VitalReadout } from "../components/VitalReadout.jsx";
import { useAsyncAction } from "../hooks/useAsyncAction.js";

const starterMessages = [
  {
    role: "assistant",
    text: "您好，我是智药康护 AI 助手。今天会结合张三的高血压档案、最近体征和药柜库存，提醒按时服药并给出居家照护建议。"
  },
  {
    role: "user",
    text: "我最近头有点晕，晚上的药还能按时吃吗？"
  },
  {
    role: "assistant",
    text: "可以先测量血压、心率和血氧。如果体征稳定，18:30 按计划服用硝苯地平控释片；若头晕明显、胸闷或血压异常，请暂停自行加药并联系家属或医生。"
  }
];

const quickPrompts = ["今天该吃哪些药？", "血氧低要注意什么？", "头晕怎么办？", "这些药能一起吃吗？"];

export function AiChatPage({ status, profile, vitals, medicines, notify }) {
  const [messages, setMessages] = useState(starterMessages);
  const [input, setInput] = useState("");
  const [activeHistory, setActiveHistory] = useState("high");
  const boxRef = useRef(null);
  const qsmOnline = Boolean(status?.qsm?.online);

  const [send, responding] = useAsyncAction(async (text = input.trim()) => {
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
          const line = part.split("\n").find((item) => item.startsWith("data:"));
          if (!line) continue;
          const data = JSON.parse(line.slice(5));
          if (data.delta) {
            reply += data.delta;
            setMessages((current) => current.map((message, idx) => (idx === current.length - 1 ? { ...message, text: reply } : message)));
          }
        }
      }
    } catch (err) {
      notify(err.message);
      setMessages((current) =>
        current.map((message, idx) => (idx === current.length - 1 ? { ...message, text: "AI 问诊暂时不可用，请稍后重试。" } : message))
      );
    }
  });

  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [messages]);

  const [listen, listening] = useAsyncAction(async () => {
    try {
      const data = await api("/api/audio/asr", formBody({ duration: 4 }));
      const text = data.text || data.transcript || data.asr?.text || data.result?.text || "";
      if (!text) throw new Error(data.detail || "没有识别到语音");
      setInput(text);
      notify("语音已转写");
    } catch (err) {
      notify(err.message);
    }
  });

  const [speakLast, speaking] = useAsyncAction(async () => {
    const last = [...messages].reverse().find((message) => message.role === "assistant" && message.text)?.text || "";
    try {
      await api("/api/audio/speak", formBody({ text: last }));
      notify("已发送到外设设备喇叭播报");
    } catch (err) {
      notify(err.message);
    }
  });

  const resetChat = () => {
    setMessages(starterMessages);
    setInput("");
  };

  const currentVitals = vitals[0] || {};
  const stockedMeds = medicines.filter((item) => Number(item.stock) > 0);
  const activeMeds = stockedMeds.slice(0, 3);
  const moreMeds = Math.max(stockedMeds.length - activeMeds.length, 0);

  return (
    <div className="ai-page">
      <GlassCard className="history-panel">
        <div className="panel-title">
          <span className="card-eyebrow">历史对话</span>
          <button onClick={resetChat}>
            <Plus size={18} />
            新建
          </button>
        </div>
        {[
          ["high", "高血压用药咨询", "06-01 14:20"],
          ["sleep", "睡眠饮食咨询", "06-30 10:15"],
          ["stomach", "胃部不适咨询", "05-30 21:30"],
          ["weight", "用药注意事项", "05-29 16:45"]
        ].map(([id, title, time]) => (
          <button key={id} className={activeHistory === id ? "active" : ""} onClick={() => setActiveHistory(id)}>
            <strong>{title}</strong>
            <span>{time}</span>
          </button>
        ))}
      </GlassCard>

      <GlassCard className="chat-panel">
        <div className="chat-heading">
          <Bot size={28} />
          <div>
            <span className="card-eyebrow">AI 健康助手</span>
            <h1>问诊对话</h1>
          </div>
          <button onClick={speakLast} disabled={!qsmOnline || speaking}>
            <Speaker size={18} />
            朗读对话
          </button>
        </div>
        <div className="chat-feed" ref={boxRef}>
          {messages.map((message, idx) => (
            <article key={`${message.role}-${idx}`} className={`chat-message ${message.role}`}>
              <div className="avatar">{message.role === "assistant" ? <Bot size={22} /> : <UserRound size={22} />}</div>
              <div className="bubble">
                <MarkdownText text={message.text} />
                <time>{idx === 0 ? "14:32" : ""}</time>
              </div>
            </article>
          ))}
        </div>
        <div className="quick-prompts">
          {quickPrompts.map((prompt) => (
            <button key={prompt} onClick={() => send(prompt)} disabled={responding}>{prompt}</button>
          ))}
        </div>
        <div className="composer">
          <button onClick={listen} disabled={!qsmOnline || listening}>
            <Mic size={24} />
          </button>
          <textarea value={input} onChange={(event) => setInput(event.target.value)} placeholder="输入您的问题..." aria-label="输入问诊问题" />
          <button className="primary" onClick={() => send()} disabled={!input.trim() || responding} aria-busy={responding || undefined}>
            <Send size={24} />
          </button>
        </div>
      </GlassCard>

      <GlassCard className="health-context-panel">
        <span className="card-eyebrow">健康档案</span>
        <div className="profile-block">
          <div className="avatar large">
            <UserRound size={28} />
          </div>
          <div>
            <h2>{profile.name || "未填写姓名"}</h2>
            <p>{profile.gender || "未填性别"} · {profile.age || "--"} 岁</p>
          </div>
        </div>
        <span className="card-eyebrow">最近体征</span>
        <VitalReadout vitals={currentVitals} />
        <span className="card-eyebrow">慢病与过敏</span>
        <div className="condition-list">
          <p><strong>慢病</strong><span>{profile.conditions || "高血压；糖尿病前期"}</span></p>
          <p><strong>过敏</strong><span>{profile.allergies || "青霉素"}</span></p>
        </div>
        <span className="card-eyebrow">正在服用</span>
        <div className="med-context-list">
          {activeMeds.length ? activeMeds.map((item) => (
            <p key={item.slot}>
              <strong>{item.name || `${item.slot} 号仓`}</strong>
              <span>{item.dosage || "未填规格"}</span>
            </p>
          )) : <p className="muted">暂无库存药品</p>}
          {moreMeds > 0 && <p className="more-meds"><strong>+{moreMeds} 项</strong><span>在药柜中</span></p>}
        </div>
        <span className="qsm-note">{qsmOnline ? "语音输入和播报可用" : "设备连接中，语音能力暂不可用"}</span>
      </GlassCard>
    </div>
  );
}
