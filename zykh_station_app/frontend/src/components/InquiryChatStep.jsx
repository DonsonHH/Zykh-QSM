import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  ClipboardCheck,
  Cpu,
  Keyboard,
  LoaderCircle,
  MessageCircle,
  Mic,
  RotateCcw,
  Send,
  ShieldCheck,
  Sparkles,
  Volume2,
  X
} from "lucide-react";
import { speakText, stopAudioPlayback } from "../api/audio.js";
import { StrokeDrawIcon } from "./StrokeDrawIcon.jsx";
import { aiSourcePresentation } from "../utils/ai.js";
import { markNetworkActivity } from "../utils/networkActivity.js";
import { VoiceEvent, VoicePhase, nextVoicePhase } from "../utils/voiceSession.js";
import { normalizeVoiceTranscript } from "../utils/voiceTranscript.js";
import { inquiryReplyStreamProfile } from "../utils/inquiryStreaming.js";
import { WxVoiceRecorderOverlay } from "./WxVoiceRecorderOverlay.jsx";

function speakLocally(text) {
  return new Promise((resolve) => {
    if (!text || !window.speechSynthesis || typeof SpeechSynthesisUtterance === "undefined") {
      resolve(false);
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "zh-CN";
    utterance.rate = 1.08;
    utterance.pitch = 1;
    utterance.onend = () => resolve(true);
    utterance.onerror = () => resolve(false);
    window.speechSynthesis.speak(utterance);
  });
}

export function InquiryChatStep({
  session,
  sending,
  notify,
  onSend,
  onReset,
  onReview,
  onReplyPlaybackStart,
  networkStatus
}) {
  const [voicePhase, setVoicePhase] = useState(VoicePhase.IDLE);
  const [voiceMessage, setVoiceMessage] = useState("请在右侧按住说话。");
  const [localPending, setLocalPending] = useState("");
  const [transcriptPreview, setTranscriptPreview] = useState("");
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  const [keyboardText, setKeyboardText] = useState("");
  const [streamedReply, setStreamedReply] = useState(session.reply || "");
  const [streaming, setStreaming] = useState(false);
  const [cancelGesture, setCancelGesture] = useState(false);
  const wsRef = useRef(null);
  const partialTextRef = useRef("");
  const finishTimerRef = useRef(null);
  const finishedRef = useRef(false);
  const voicePhaseRef = useRef(VoicePhase.IDLE);
  const bottomRef = useRef(null);
  const playbackGenerationRef = useRef(0);
  const holdActiveRef = useRef(false);
  const holdStartYRef = useRef(0);
  const cancelGestureRef = useRef(false);
  const preservePlaybackOnExitRef = useRef(false);

  const preparingVoice = voicePhase === VoicePhase.PREPARING;
  const listening = voicePhase === VoicePhase.LISTENING;
  const transcribingVoice = voicePhase === VoicePhase.TRANSCRIBING;
  const voiceOverlayOpen = preparingVoice || listening || transcribingVoice || Boolean(transcriptPreview);
  const streamProfile = inquiryReplyStreamProfile(session.source);
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
      index = Math.min(reply.length, index + streamProfile.chunkSize);
      setStreamedReply(reply.slice(0, index));
      if (index >= reply.length) {
        window.clearInterval(timer);
        setStreaming(false);
        playReply(reply, true);
      }
    }, streamProfile.intervalMs);
    return () => window.clearInterval(timer);
  }, [session.reply, streamProfile.chunkSize, streamProfile.intervalMs]);

  useEffect(() => () => {
    stopVoice(false);
    if (!preservePlaybackOnExitRef.current) interruptPlayback();
  }, []);

  useEffect(() => {
    const release = (event) => {
      if (holdActiveRef.current) handleHoldEnd(event);
    };
    const move = (event) => {
      if (!holdActiveRef.current || !Number.isFinite(event.clientY)) return;
      event.preventDefault();
      const shouldCancel = holdStartYRef.current - event.clientY >= 84;
      if (shouldCancel === cancelGestureRef.current) return;
      cancelGestureRef.current = shouldCancel;
      setCancelGesture(shouldCancel);
    };
    const cancel = (event) => {
      if (holdActiveRef.current) handleHoldCancel(event);
    };
    window.addEventListener("pointerup", release);
    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointercancel", cancel);
    return () => {
      window.removeEventListener("pointerup", release);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointercancel", cancel);
    };
  }, []);

  async function playReply(text, announceVitals = false) {
    if (!text) return;
    const generation = playbackGenerationRef.current + 1;
    playbackGenerationRef.current = generation;
    preservePlaybackOnExitRef.current = false;
    window.speechSynthesis?.cancel();
    await stopAudioPlayback().catch(() => null);
    if (generation !== playbackGenerationRef.current) return;
    if (announceVitals && session.next_action === "measure_vitals") {
      preservePlaybackOnExitRef.current = true;
      onReplyPlaybackStart?.();
    }
    try {
      const result = await speakText(text, undefined, 1.12, "auto");
      if (!result?.ok) throw new Error(result?.message || "语音播报未完成");
    } catch {
      if (generation === playbackGenerationRef.current) await speakLocally(text);
    }
  }

  function interruptPlayback() {
    preservePlaybackOnExitRef.current = false;
    playbackGenerationRef.current += 1;
    window.speechSynthesis?.cancel();
    stopAudioPlayback().catch(() => null);
  }

  async function send(text) {
    const content = String(text || "").trim();
    if (!content || sending || streaming) return;
    setLocalPending(content);
    setTranscriptPreview("");
    setKeyboardText("");
    setKeyboardOpen(false);
    setVoiceMessage("已发送，正在整理关键信息。");
    try {
      await onSend(content);
    } finally {
      setLocalPending("");
    }
  }

  async function startVoice() {
    interruptPlayback();
    if (voicePhaseRef.current !== VoicePhase.IDLE || sending || streaming) return;

    finishedRef.current = false;
    partialTextRef.current = "";
    setTranscriptPreview("");
    setKeyboardOpen(false);
    moveVoice(VoiceEvent.START);
    setVoiceMessage("正在连接麦克风，请看到“正在听”后再说话。");
    try {
      markNetworkActivity("upload");
      const ws = new WebSocket(websocketUrl("/api/audio/asr/realtime?mode=cloud"));
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
      if (!holdActiveRef.current) {
        stopVoice(false);
        setVoiceMessage("请长按语音按钮，看到“正在听”后再说话。");
        return;
      }
      moveVoice(VoiceEvent.READY);
      setVoiceMessage(data.offline ? "本地识别正在听，请自然说话。" : "正在听，请自然说话。");
      return;
    }
    if (data.type === "error") {
      failVoice(data.message || "实时语音识别暂不可用。");
      return;
    }
    if (data.type === "transcript" && data.text) {
      partialTextRef.current = data.text;
      if (voicePhaseRef.current === VoicePhase.LISTENING) {
        setVoiceMessage("正在听，请继续说话，松开后再识别。");
      } else {
        setVoiceMessage(data.final ? "语音已转成文字，请核对后发送。" : "正在整理语音...");
      }
      if (data.final && voicePhaseRef.current === VoicePhase.TRANSCRIBING) {
        completeTranscriptPreview(data.text);
      }
    }
  }

  function completeTranscriptPreview(text) {
    if (finishedRef.current) return;
    finishedRef.current = true;
    stopVoice(false);
    const content = normalizeVoiceTranscript(text || partialTextRef.current);
    if (content) {
      setTranscriptPreview(content);
      setVoiceMessage("请核对识别文字，可以发送或重新录音。");
    } else {
      setVoiceMessage("未识别到有效语音，请再试一次。");
    }
  }

  function stopVoice(commit = true) {
    window.clearTimeout(finishTimerRef.current);
    const ws = wsRef.current;
    if (commit && voicePhaseRef.current === VoicePhase.LISTENING && ws?.readyState === WebSocket.OPEN) {
      moveVoice(VoiceEvent.STOP);
      markNetworkActivity("upload");
      ws.send(JSON.stringify({ type: "stop" }));
      setVoiceMessage("正在生成语音文字...");
      finishTimerRef.current = window.setTimeout(() => completeTranscriptPreview(partialTextRef.current), 6000);
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
    playReply(session.reply || "", session.next_action === "measure_vitals");
  }

  function handleHoldStart(event) {
    if (sending || transcribingVoice) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    holdActiveRef.current = true;
    holdStartYRef.current = Number.isFinite(event.clientY) ? event.clientY : 0;
    cancelGestureRef.current = false;
    setCancelGesture(false);
    startVoice();
  }

  function handleHoldEnd(event) {
    event.preventDefault();
    if (!holdActiveRef.current) return;
    holdActiveRef.current = false;
    const shouldCancel = cancelGestureRef.current;
    cancelGestureRef.current = false;
    setCancelGesture(false);
    if (shouldCancel) {
      stopVoice(false);
      setVoiceMessage("录音已取消。");
      return;
    }
    if (voicePhaseRef.current === VoicePhase.LISTENING) {
      stopVoice(true);
      return;
    }
    if (voicePhaseRef.current === VoicePhase.PREPARING) {
      stopVoice(false);
      setVoiceMessage("麦克风还没准备好，请重新长按并等待“正在听”。");
    }
  }

  function handleHoldCancel(event) {
    event.preventDefault();
    if (!holdActiveRef.current) return;
    holdActiveRef.current = false;
    cancelGestureRef.current = false;
    setCancelGesture(false);
    stopVoice(false);
    setVoiceMessage("录音已取消。");
  }

  function closeVoiceOverlay() {
    holdActiveRef.current = false;
    cancelGestureRef.current = false;
    setCancelGesture(false);
    stopVoice(false);
    setTranscriptPreview("");
    setVoiceMessage("请在右侧按住说话。");
  }

  function submitKeyboard(event) {
    event.preventDefault();
    send(keyboardText);
  }

  return (
    <section className="inquiry-chat-step voice-only" aria-label="AI 对话问询">
      <section className="chat-main-panel">
        <div className="chat-title-row">
          <span className="chat-assistant-motion" aria-hidden="true"><Bot size={26} /></span>
          <div><h2>AI问询 · {session.user_name}</h2></div>
          <div className="chat-icon-actions">
            <button type="button" className="chat-speak-button icon-only" onClick={onReview} aria-label="核对本次问询信息"><ClipboardCheck size={21} aria-hidden="true" /></button>
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
                <div className="chat-message-line">
                  {message.role === "assistant" && message.source ? <MessageSource source={message.source} /> : null}
                  <p>{content || "正在整理..."}</p>
                </div>
              </article>
            );
          })}
          {localPending ? <article className="chat-bubble user"><p>{localPending}</p></article> : null}
          {sending ? <article className="chat-bubble assistant thinking"><StrokeDrawIcon icon={Bot} size={20} strokeWidth={2} mode="yoyo" /><p>正在整理关键信息...</p></article> : null}
          <span ref={bottomRef} />
        </div>

        {keyboardOpen ? (
          <form className="chat-keyboard-entry" onSubmit={submitKeyboard}>
            <input
              autoFocus
              type="text"
              inputMode="text"
              lang="zh-CN"
              enterKeyHint="send"
              autoCapitalize="none"
              value={keyboardText}
              onChange={(event) => setKeyboardText(event.target.value)}
              placeholder="使用屏幕键盘补充一句话"
              aria-label="手动输入问询内容"
            />
            <button type="button" className="icon-action" onClick={() => setKeyboardOpen(false)} aria-label="关闭键盘输入"><X size={21} /></button>
            <button type="submit" className="primary-action" disabled={!keyboardText.trim() || sending || streaming}><Send size={20} />发送</button>
          </form>
        ) : (
          <div className="chat-voice-bar hold-to-talk">
            <div className={`voice-status chat-voice-status ${preparingVoice ? "preparing" : listening ? "listening" : transcribingVoice || sending ? "processing" : ""}`} aria-live="polite">{voiceMessage}</div>
            <button type="button" className="chat-keyboard-button" onClick={() => setKeyboardOpen(true)} disabled={streaming} aria-label="打开屏幕键盘"><Keyboard size={24} /></button>
            <button
              className={`voice-chat-button compact ${preparingVoice ? "preparing" : listening ? "listening" : transcribingVoice || sending ? "processing" : ""}`}
              type="button"
              onPointerDown={handleHoldStart}
              onPointerUp={handleHoldEnd}
              onPointerCancel={handleHoldCancel}
              onContextMenu={(event) => event.preventDefault()}
              disabled={sending || transcribingVoice || streaming}
              aria-pressed={listening}
            >
              {listening ? <StrokeDrawIcon icon={Mic} size={23} strokeWidth={2.2} mode="yoyo" />
                : preparingVoice ? <LoaderCircle className="voice-preparing-spinner" size={23} aria-hidden="true" />
                  : <Mic size={23} aria-hidden="true" />}
              {sending ? "AI 正在整理" : transcribingVoice ? "正在识别" : preparingVoice ? "保持按住 · 正在准备" : listening ? "正在听 · 松开结束" : "按住说话"}
            </button>
          </div>
        )}
      </section>
      {voiceOverlayOpen ? (
        <WxVoiceRecorderOverlay
          phase={listening ? "listening" : preparingVoice ? "preparing" : transcribingVoice ? "processing" : "review"}
          message={voiceMessage}
          transcript={transcriptPreview}
          cancelGesture={cancelGesture}
          sending={sending}
          onClose={closeVoiceOverlay}
          onCancelSend={closeVoiceOverlay}
          onSend={() => send(transcriptPreview)}
        />
      ) : null}
    </section>
  );
}

function MessageSource({ source }) {
  const presentation = aiSourcePresentation(source);
  const Icon = presentation.kind === "smart"
    ? Sparkles
    : presentation.kind === "local"
      ? Cpu
      : presentation.kind === "safety"
        ? ShieldCheck
        : MessageCircle;
  return (
    <span
      className={`chat-source-icon ${presentation.kind}`}
      role="img"
      aria-label={presentation.label}
      title={presentation.label}
    >
      <Icon size={14} aria-hidden="true" />
    </span>
  );
}

function websocketUrl(path) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${path}`;
}
