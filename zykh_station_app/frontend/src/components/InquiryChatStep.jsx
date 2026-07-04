import React, { useEffect, useMemo, useRef, useState } from "react";
import { Activity, Bot, Mic, RotateCcw, Send, Volume2 } from "lucide-react";
import { askAssistant } from "../api/ai.js";
import { speakText } from "../api/audio.js";
import { SymptomQuickChips } from "./SymptomQuickChips.jsx";

const introMessage = {
  role: "assistant",
  content:
    "我是 AI 康护助手。请先说出哪里不舒服，我会一步步追问持续时间、已用药、过敏禁忌和体征信息。"
};

function speakLocally(text) {
  if (!text || !window.speechSynthesis || typeof SpeechSynthesisUtterance === "undefined") {
    return false;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 0.96;
  utterance.pitch = 1;
  window.speechSynthesis.speak(utterance);
  return true;
}

export function InquiryChatStep({ notify, onStructuredAnalyze, onOpenVitals }) {
  const [messages, setMessages] = useState([introMessage]);
  const [draft, setDraft] = useState("");
  const [listening, setListening] = useState(false);
  const [sending, setSending] = useState(false);
  const [voiceMessage, setVoiceMessage] = useState("");
  const recognitionRef = useRef(null);
  const bottomRef = useRef(null);

  const transcript = useMemo(
    () =>
      messages
        .filter((message) => message.role === "user")
        .map((message) => message.content)
        .join("；"),
    [messages]
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "nearest" });
  }, [messages, sending]);

  function appendMessage(message) {
    setMessages((current) => [...current, message]);
  }

  function buildPrompt(text) {
    return [
      "请以对话方式引导家庭成员完成应急问询。一次只问一个关键问题。",
      "需要逐步确认：症状、持续时间、已用药、过敏禁忌、是否需要读取体征。",
      "回答要短，像现场值守康护人员一样清楚温和。",
      "不能替代医生，不能让用户直接服用某个药，只能提示风险和候选类别。",
      `本次用户输入：${text}`,
      `已知对话：${transcript || "暂无"}`
    ].join("\n");
  }

  function send(text = draft) {
    const content = text.trim();
    if (!content || sending) {
      return;
    }
    setDraft("");
    appendMessage({ role: "user", content });
    setSending(true);
    askAssistant(buildPrompt(content))
      .then((data) => {
        const reply = data.reply || "我已记录，请继续补充持续时间、已用药和过敏禁忌信息。";
        appendMessage({ role: "assistant", content: reply, source: data.source || "local_fallback" });
        if (!speakLocally(reply)) {
          speakText(reply, 230).catch(() => {});
        }
      })
      .catch((error) => {
        const fallback = error.message || "对话暂不可用，请使用引导问询流程。";
        appendMessage({ role: "assistant", content: fallback, source: "local_fallback" });
        notify(fallback);
      })
      .finally(() => setSending(false));
  }

  function startVoice() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      const message = "当前语音输入不可用，请点击症状按钮。";
      setVoiceMessage(message);
      notify(message);
      return;
    }
    if (recognitionRef.current) {
      recognitionRef.current.abort();
      recognitionRef.current = null;
    }
    const recognition = new Recognition();
    recognition.lang = "zh-CN";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognitionRef.current = recognition;
    setListening(true);
    setVoiceMessage("正在听，请直接说出症状或回答 AI 的问题。");
    recognition.onresult = (event) => {
      const text = Array.from(event.results)
        .map((resultItem) => resultItem[0]?.transcript || "")
        .join("")
        .trim();
      if (text) {
        send(text);
        setVoiceMessage("语音已发送。");
      } else {
        setVoiceMessage("未识别到有效语音，请再试一次。");
      }
    };
    recognition.onerror = () => {
      const message = "当前语音输入不可用，请点击症状按钮。";
      setVoiceMessage(message);
      notify(message);
    };
    recognition.onend = () => {
      setListening(false);
      recognitionRef.current = null;
    };
    recognition.start();
  }

  function reset() {
    window.speechSynthesis?.cancel();
    setMessages([introMessage]);
    setDraft("");
    setVoiceMessage("");
  }

  return (
    <section className="inquiry-chat-step" aria-label="AI 对话问询">
      <aside className="chat-quick-panel">
        <strong>快速开始</strong>
        <SymptomQuickChips selected="" onSelect={send} />
        <button type="button" onClick={onOpenVitals}>
          <Activity size={22} aria-hidden="true" />
          读取体征
        </button>
        <button type="button" onClick={reset}>
          <RotateCcw size={22} aria-hidden="true" />
          重新对话
        </button>
      </aside>

      <section className="chat-main-panel">
        <div className="chat-title-row">
          <span aria-hidden="true">
            <Bot size={26} />
          </span>
          <div>
            <p>AI 对话问询</p>
            <h2>像聊天一样逐步说明身体状态</h2>
          </div>
          <button type="button" className="chat-speak-button" onClick={() => speakLocally(messages.at(-1)?.content || "")}>
            <Volume2 size={21} aria-hidden="true" />
            重播
          </button>
        </div>

        <div className="chat-thread" aria-live="polite">
          {messages.map((message, index) => (
            <article key={`${message.role}-${index}`} className={`chat-bubble ${message.role}`}>
              <p>{message.content}</p>
              {message.source ? <small>{message.source === "cloud" ? "云通道" : "本地兜底"}</small> : null}
            </article>
          ))}
          {sending ? (
            <article className="chat-bubble assistant thinking">
              <p>正在整理你的信息...</p>
            </article>
          ) : null}
          <span ref={bottomRef} />
        </div>

        <div className="chat-input-row">
          <button className="voice-chat-button" type="button" onClick={startVoice} disabled={listening || sending}>
            <Mic size={24} aria-hidden="true" />
            {listening ? "正在听" : "语音回答"}
          </button>
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                send();
              }
            }}
            placeholder="也可以短句输入"
          />
          <button className="send-chat-button" type="button" onClick={() => send()} disabled={sending || !draft.trim()}>
            <Send size={22} aria-hidden="true" />
            发送
          </button>
        </div>
        {voiceMessage ? <div className="voice-status chat-voice-status">{voiceMessage}</div> : null}
        <button className="primary-action chat-analyze-button" type="button" onClick={() => onStructuredAnalyze(transcript)} disabled={!transcript.trim()}>
          转为结构化分析
        </button>
      </section>
    </section>
  );
}
