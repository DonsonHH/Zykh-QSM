import React, { useEffect, useMemo, useRef, useState } from "react";
import { Bot, LoaderCircle, Mic, RotateCcw, Volume2 } from "lucide-react";
import { speakText, stopAudioPlayback } from "../api/audio.js";
import { StrokeDrawIcon } from "./StrokeDrawIcon.jsx";
import { aiSourceLabel } from "../utils/ai.js";
import { isLocalNetworkMode } from "../utils/network.js";
import { markNetworkActivity } from "../utils/networkActivity.js";
import { VoiceEvent, VoicePhase, nextVoicePhase } from "../utils/voiceSession.js";

function speakLocally(text) {
  if (!text || !window.speechSynthesis || typeof SpeechSynthesisUtterance === "undefined") return false;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 1.08;
  utterance.pitch = 1;
  window.speechSynthesis.speak(utterance);
  return true;
}

export function InquiryChatStep({ session, sending, notify, onSend, onReset, networkStatus }) {
  const [voicePhase, setVoicePhase] = useState(VoicePhase.IDLE);
  const [voiceMessage, setVoiceMessage] = useState("点击按钮开始语音问询。");
  const [localPending, setLocalPending] = useState("");
  const [streamedReply, setStreamedReply] = useState(session.reply || "");
  const [streaming, setStreaming] = useState(false);
  const wsRef = useRef(null);
  const partialTextRef = useRef("");
  const finishTimerRef = useRef(null);
  const listenTimerRef = useRef(null);
  const finishedRef = useRef(false);
  const voicePhaseRef = useRef(VoicePhase.IDLE);
  const bottomRef = useRef(null);
  const playbackGenerationRef = useRef(0);

  const preparingVoice = voicePhase === VoicePhase.PREPARING;
  const listening = voicePhase === VoicePhase.LISTENING;
  const transcribingVoice = voicePhase === VoicePhase.TRANSCRIBING;
  const lastAssistantId = useMemo(
    () => [...(session.messages || [])].reverse().find((message) => message.role === "assistant")?.id || "",
    [session.messages]
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [localPending, sending, session.messages, streamedReply]);

  useEffect(() => {
    const reply = session.reply || "";
    if (!reply) return undefined;
    setStreaming(true);
    setStreamedReply("");
    let index = 0;
    const timer = window.setInterval(() => {
      index = Math.min(reply.length, index + 4);
      setStreamedReply(reply.slice(0, index));
      if (index >= reply.length) {
        window.clearInterval(timer);
        setStreaming(false);
        playReply(reply);
      }
    }, 42);
    return () => window.clearInterval(timer);
  }, [session.reply]);

  useEffect(() => () => {
    stopVoice(false);
    interruptPlayback();
  }, []);

  async function playReply(text) {
    if (!text) return;
    const generation = playbackGenerationRef.current + 1;
    playbackGenerationRef.current = generation;
    window.speechSynthesis?.cancel();
    await stopAudioPlayback().catch(() => null);
    if (generation !== playbackGenerationRef.current) return;
    const mode = isLocalNetworkMode(networkStatus) ? "offline" : "auto";
    try {
      await speakText(text, undefined, 1.12, mode);
    } catch {
      if (generation === playbackGenerationRef.current) speakLocally(text);
    }
  }

  function interruptPlayback() {
    playbackGenerationRef.current += 1;
    window.speechSynthesis?.cancel();
    stopAudioPlayback().catch(() => null);
  }

  async function send(text) {
    const content = String(text || "").trim();
    if (!content || sending) return;
    setLocalPending(content);
    setVoiceMessage("已发送，正在整理关键信息。");
    try {
      await onSend(content);
    } finally {
      setLocalPending("");
    }
  }

  async function startVoice() {
    interruptPlayback();
    if (voicePhaseRef.current === VoicePhase.PREPARING) {
      stopVoice(false);
      setVoiceMessage("已取消，点击按钮可重新开始。");
      return;
    }
    if (voicePhaseRef.current === VoicePhase.LISTENING) {
      stopVoice(true);
      return;
    }
    if (voicePhaseRef.current !== VoicePhase.IDLE || sending) return;

    finishedRef.current = false;
    partialTextRef.current = "";
    moveVoice(VoiceEvent.START);
    setVoiceMessage("正在连接麦克风，请看到“正在听”后再说话。");
    try {
      const runtimeMode = isLocalNetworkMode(networkStatus) ? "local" : "cloud";
      markNetworkActivity("upload");
      const ws = new WebSocket(websocketUrl(`/api/audio/asr/realtime?mode=${runtimeMode}`));
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;
      ws.onopen = () => setVoiceMessage("正在准备语音识别...");
      ws.onmessage = (event) => handleVoiceEvent(event);
      ws.onerror = () => failVoice("实时语音识别连接失败，请检查麦克风服务。");
      ws.onclose = () => {
        if (voicePhaseRef.current !== VoicePhase.IDLE && !finishedRef.current) moveVoice(VoiceEvent.FAIL);
      };
    } catch (error) {
      failVoice(error?.message || "麦克风启动失败，请检查设备连接。");
    }
  }

  function handleVoiceEvent(event) {
    markNetworkActivity("download");
    let data;
    try {
      data = JSON.parse(event.data || "{}");
    } catch {
      return;
    }
    if (data.type === "preparing") {
      setVoiceMessage(data.message || "正在准备语音识别...");
      return;
    }
    if (data.type === "ready") {
      if (voicePhaseRef.current !== VoicePhase.PREPARING) return;
      moveVoice(VoiceEvent.READY);
      setVoiceMessage(data.offline ? "本地识别正在听，请自然说话。" : "正在听，请自然说话。");
      window.clearTimeout(listenTimerRef.current);
      listenTimerRef.current = window.setTimeout(() => stopVoice(true), 12000);
      return;
    }
    if (data.type === "error") {
      failVoice(data.message || "实时语音识别暂不可用。");
      return;
    }
    if (data.type === "transcript" && data.text) {
      partialTextRef.current = data.text;
      setVoiceMessage(data.final ? `识别完成：${data.text}` : `识别中：${data.text}`);
      if (data.final) finishVoice(data.text);
    }
  }

  function finishVoice(text) {
    if (finishedRef.current) return;
    finishedRef.current = true;
    stopVoice(false);
    const content = String(text || partialTextRef.current || "").trim();
    if (content) {
      send(content);
    } else {
      setVoiceMessage("未识别到有效语音，请再试一次。");
    }
  }

  function stopVoice(commit = true) {
    window.clearTimeout(finishTimerRef.current);
    window.clearTimeout(listenTimerRef.current);
    const ws = wsRef.current;
    if (commit && voicePhaseRef.current === VoicePhase.LISTENING && ws?.readyState === WebSocket.OPEN) {
      moveVoice(VoiceEvent.STOP);
      markNetworkActivity("upload");
      ws.send(JSON.stringify({ type: "stop" }));
      setVoiceMessage("正在生成语音文字...");
      finishTimerRef.current = window.setTimeout(() => finishVoice(partialTextRef.current), 6000);
    } else if (ws && ws.readyState <= WebSocket.OPEN) {
      ws.close();
    }
    if (!commit || voicePhaseRef.current === VoicePhase.PREPARING) moveVoice(VoiceEvent.CANCEL);
    wsRef.current = null;
  }

  function failVoice(message) {
    setVoiceMessage(message);
    notify(message);
    stopVoice(false);
  }

  function moveVoice(event) {
    const next = nextVoicePhase(voicePhaseRef.current, event);
    voicePhaseRef.current = next;
    setVoicePhase(next);
  }

  function replay() {
    playReply(session.reply || "");
  }

  return (
    <section className="inquiry-chat-step voice-only" aria-label="AI 对话问询">
      <section className="chat-main-panel">
        <div className="chat-title-row">
          <span className="chat-assistant-motion" aria-hidden="true"><Bot size={26} /></span>
          <div><h2>AI问询 · {session.user_name}</h2></div>
          <div className="chat-icon-actions">
            <button type="button" className="chat-speak-button icon-only" onClick={replay} aria-label="重播最近回复"><Volume2 size={21} aria-hidden="true" /></button>
            <button type="button" className="chat-speak-button icon-only" onClick={onReset} aria-label="重新对话并确认使用人"><RotateCcw size={21} aria-hidden="true" /></button>
          </div>
        </div>

        <div className="chat-thread" aria-live="polite">
          {(session.messages || []).map((message) => {
            const isLastAssistant = message.id === lastAssistantId;
            const content = isLastAssistant ? streamedReply : message.content;
            return (
              <article key={message.id} className={`chat-bubble ${message.role} ${isLastAssistant && streaming ? "streaming" : ""}`}>
                <p>{content || "正在整理..."}</p>
                {message.source ? <small>{aiSourceLabel(message.source)}</small> : null}
              </article>
            );
          })}
          {localPending ? <article className="chat-bubble user"><p>{localPending}</p></article> : null}
          {sending ? <article className="chat-bubble assistant thinking"><StrokeDrawIcon icon={Bot} size={20} strokeWidth={2} mode="yoyo" /><p>正在整理关键信息...</p></article> : null}
          <span ref={bottomRef} />
        </div>

        <div className="chat-voice-bar">
          <button className={`voice-chat-button compact ${preparingVoice ? "preparing" : listening ? "listening" : transcribingVoice || sending ? "processing" : ""}`} type="button" onClick={startVoice} disabled={sending || transcribingVoice} aria-pressed={listening}>
            {listening ? <StrokeDrawIcon icon={Mic} size={23} strokeWidth={2.2} mode="yoyo" />
              : preparingVoice ? <LoaderCircle className="voice-preparing-spinner" size={23} aria-hidden="true" />
                : <Mic size={23} aria-hidden="true" />}
            {sending ? "AI 正在整理" : transcribingVoice ? "正在识别" : preparingVoice ? "正在准备 · 点击取消" : listening ? "正在听 · 点击发送" : "点击开始说话"}
          </button>
          <div className={`voice-status chat-voice-status ${preparingVoice ? "preparing" : listening ? "listening" : transcribingVoice || sending ? "processing" : ""}`} aria-live="polite">{voiceMessage}</div>
        </div>
      </section>
    </section>
  );
}

function websocketUrl(path) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${path}`;
}
