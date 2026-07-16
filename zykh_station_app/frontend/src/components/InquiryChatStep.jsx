import React, { useEffect, useMemo, useRef, useState } from "react";
import { Bot, LoaderCircle, Mic, RotateCcw, Volume2 } from "lucide-react";
import { speakText } from "../api/audio.js";
import { StrokeDrawIcon } from "./StrokeDrawIcon.jsx";
import { aiSourceLabel } from "../utils/ai.js";
import { isLocalNetworkMode } from "../utils/network.js";
import { markNetworkActivity } from "../utils/networkActivity.js";
import { VoiceEvent, VoicePhase, nextVoicePhase } from "../utils/voiceSession.js";

const chatDraftKey = "zykh-inquiry-chat-draft";
const vitalsAwaitingKey = "zykh-inquiry-awaiting-vitals";
const latestVitalsKey = "zykh-latest-vitals";

function initialMessages(profile, history) {
  const intro = {
    role: "assistant",
    content: profile
      ? `已匹配到${profile.name}。请直接说出现在最不舒服的地方。`
      : "正在通过人脸确认使用人，请正对摄像头。确认后即可直接说出不舒服的地方。"
  };
  if (!history?.seed?.length) {
    return [intro];
  }
  return [
    intro,
    { role: "assistant", content: `已打开历史问询：${history.title}。请继续补充现在的变化。` },
    ...history.seed
  ];
}

function readChatDraft() {
  try {
    const raw = window.sessionStorage.getItem(chatDraftKey);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function speakLocally(text) {
  if (!text || !window.speechSynthesis || typeof SpeechSynthesisUtterance === "undefined") {
    return false;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 1.28;
  utterance.pitch = 1;
  window.speechSynthesis.speak(utterance);
  return true;
}

function lastAssistantMessage(messages) {
  return [...messages].reverse().find((message) => message.role === "assistant")?.content || "";
}

function transcriptFrom(messages) {
  return messages
    .filter((message) => message.role === "user")
    .map((message) => message.content)
    .join("；");
}

function readLatestVitals() {
  try {
    const raw = window.sessionStorage.getItem(latestVitalsKey);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function describeVitals(data) {
  if (!data || data.ok === false || data.status === "unavailable") {
    return "";
  }
  const parts = [
    data.temperature ? `体温${data.temperature}℃` : "",
    data.heart_rate ? `心率${data.heart_rate}次/分` : "",
    data.spo2 ? `血氧${data.spo2}%` : ""
  ].filter(Boolean);
  return parts.join("，");
}

function cleanAssistantReply(text) {
  return text
    .replace(/\[READY_FOR_SAFETY_ANALYSIS\]/g, "")
    .replace(/\[NEED_VITALS\]/g, "")
    .trim();
}

export function InquiryChatStep({
  notify,
  onStructuredAnalyze,
  onOpenVitals,
  onDemoRecommendation,
  profile,
  history,
  networkStatus
}) {
  const draft = readChatDraft();
  const [messages, setMessages] = useState(() => draft?.messages || initialMessages(profile, history));
  const [activeProfile, setActiveProfile] = useState(() => profile || draft?.profile || null);
  const [voicePhase, setVoicePhase] = useState(VoicePhase.IDLE);
  const [sending, setSending] = useState(false);
  const [voiceMessage, setVoiceMessage] = useState("点击按钮开始语音问询。");
  const [vitalsSummary, setVitalsSummary] = useState(() => draft?.vitalsSummary || describeVitals(readLatestVitals()));
  const bottomRef = useRef(null);
  const wsRef = useRef(null);
  const partialTextRef = useRef("");
  const finishTimerRef = useRef(null);
  const finishedRef = useRef(false);
  const waitingForVitalsRef = useRef(false);
  const profileRef = useRef(activeProfile);
  const voicePhaseRef = useRef(VoicePhase.IDLE);

  const preparingVoice = voicePhase === VoicePhase.PREPARING;
  const listening = voicePhase === VoicePhase.LISTENING;
  const transcribingVoice = voicePhase === VoicePhase.TRANSCRIBING;

  const transcript = useMemo(() => transcriptFrom(messages), [messages]);

  useEffect(() => {
    profileRef.current = activeProfile;
  }, [activeProfile]);

  useEffect(() => {
    if (profile?.id && !profileRef.current?.id) {
      setActiveProfile(profile);
      setMessages((current) => {
        const confirmation = { role: "assistant", content: `已确认使用人：${profile.name}。请直接说出现在最不舒服的地方。` };
        if (current[0]?.role === "assistant" && current[0]?.content?.startsWith("正在通过人脸确认")) {
          return [confirmation, ...current.slice(1)];
        }
        return [...current, confirmation];
      });
    }
  }, [profile]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "nearest" });
    try {
      window.sessionStorage.setItem(chatDraftKey, JSON.stringify({ messages, profile: activeProfile, vitalsSummary }));
    } catch {
      // Draft storage is optional.
    }
  }, [activeProfile, messages, sending, vitalsSummary]);

  useEffect(() => {
    const awaiting = window.sessionStorage.getItem(vitalsAwaitingKey) === "1";
    const latest = readLatestVitals();
    const summary = describeVitals(latest);
    if (awaiting && summary) {
      window.sessionStorage.removeItem(vitalsAwaitingKey);
      setVitalsSummary(summary);
      appendMessage({ role: "assistant", content: `体征测量完成：${summary}。请说现在最不舒服的地方。` });
      waitingForVitalsRef.current = false;
    }
    return () => stopVoice(false);
  }, []);

  function appendMessage(message) {
    setMessages((current) => [...current, message]);
  }

  function updateLastAssistant(content, extra = {}) {
    setMessages((current) => {
      const next = [...current];
      for (let index = next.length - 1; index >= 0; index -= 1) {
        if (next[index].role === "assistant") {
          next[index] = { ...next[index], content, ...extra };
          return next;
        }
      }
      return [...next, { role: "assistant", content, ...extra }];
    });
  }

  function isDemoHeatDizzy(content, currentProfile) {
    return currentProfile?.name === "张三" && /中暑|头晕|头昏|暑热|暑湿/.test(content);
  }

  function playReply(text) {
    const clean = cleanAssistantReply(text);
    if (!clean) {
      return;
    }
    speakText(clean, undefined, 1.32, isLocalNetworkMode(networkStatus) ? "offline" : "auto")
      .then((data) => {
        if (!data.ok) {
          speakLocally(clean);
        }
      })
      .catch(() => speakLocally(clean));
  }

  async function resolveProfile(content) {
    if (profileRef.current?.id) {
      return profileRef.current;
    }
    appendMessage({ role: "assistant", content: "人脸身份尚未确认，请正对摄像头并稍候。" });
    playReply("人脸身份尚未确认，请正对摄像头并稍候。");
    return null;
  }

  async function send(text) {
    const content = text.trim();
    if (!content || sending) {
      return;
    }
    const nextMessages = [...messages, { role: "user", content }];
    setMessages(nextMessages);
    setSending(true);

    const currentProfile = await resolveProfile(content);
    if (!currentProfile) {
      setSending(false);
      return;
    }

    if (!vitalsSummary && !waitingForVitalsRef.current) {
      waitingForVitalsRef.current = true;
      window.sessionStorage.setItem(vitalsAwaitingKey, "1");
      const prompt = "接下来需要测量体温、心率和血氧。我会打开体征测量页面，请按屏幕提示操作。";
      appendMessage({ role: "assistant", content: prompt });
      playReply(prompt);
      window.setTimeout(() => onOpenVitals?.(), 900);
      setSending(false);
      return;
    }

    if (isDemoHeatDizzy(content, currentProfile)) {
      const reply = "已记录张三中暑头晕，并结合体征信息完成用药安全核验。推荐查看 8 号柜藿香正气丸，请等待确认后开柜。";
      setMessages([...nextMessages, { role: "assistant", content: reply, source: "cloud" }]);
      playReply(reply);
      onDemoRecommendation?.({
        profile: currentProfile,
        transcript: transcriptFrom(nextMessages),
        medicineId: "slot-08-huoxiang-zhengqi",
        slot: 8
      });
      setSending(false);
      return;
    }

    await streamAssistant(content, nextMessages, currentProfile);
    setSending(false);
  }

  async function streamAssistant(message, currentMessages, currentProfile) {
    const placeholderId = `assistant-${Date.now()}`;
    setMessages([...currentMessages, { id: placeholderId, role: "assistant", content: "", source: "cloud", streaming: true }]);
    let fullText = "";
    let streamSource = "cloud";
    try {
      markNetworkActivity("upload");
      const response = await fetch("/api/ai/chat/stream", {
        method: "POST",
        headers: {
          Accept: "text/event-stream",
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          message,
          context: {
            profile: currentProfile,
            vitals: vitalsSummary,
            transcript: transcriptFrom(currentMessages)
          }
        })
      });
      if (!response.ok || !response.body) {
        throw new Error(`请求失败：${response.status}`);
      }
      markNetworkActivity("download");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        markNetworkActivity("download");
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() || "";
        for (const event of events) {
          const eventType = event
            .split("\n")
            .find((line) => line.startsWith("event: "))
            ?.slice(7)
            .trim();
          const dataLine = event.split("\n").find((line) => line.startsWith("data: "));
          if (!dataLine) {
            continue;
          }
          const data = JSON.parse(dataLine.slice(6));
          if (data.source) {
            streamSource = data.source;
          }
          if (eventType === "replace" && typeof data.text === "string") {
            fullText = data.text;
            updateLastAssistant(cleanAssistantReply(fullText), { source: streamSource, streaming: true });
            continue;
          }
          if (eventType === "done" && data.reply && !fullText) {
            fullText = data.reply;
          }
          if (data.text) {
            fullText += data.text;
            updateLastAssistant(cleanAssistantReply(fullText), { source: streamSource, streaming: true });
          }
        }
      }
    } catch (error) {
      streamSource = "rules_fallback";
      fullText = error.message || "对话暂不可用，我会使用安全规则继续整理信息。";
      updateLastAssistant(fullText, { source: "rules_fallback", streaming: false });
      notify(fullText);
    }
    const clean = cleanAssistantReply(fullText) || "我已记录，请继续补充。";
    updateLastAssistant(clean, { source: streamSource, streaming: false });
    playReply(clean);
    if (fullText.includes("[NEED_VITALS]") && !vitalsSummary) {
      window.sessionStorage.setItem(vitalsAwaitingKey, "1");
      window.setTimeout(() => onOpenVitals?.(), 900);
      return;
    }
    if (fullText.includes("[READY_FOR_SAFETY_ANALYSIS]")) {
      window.setTimeout(() => {
        onStructuredAnalyze(transcriptFrom([...currentMessages, { role: "assistant", content: clean }]), {
          includeVitals: Boolean(vitalsSummary),
          profile: currentProfile
        });
      }, 650);
    }
  }

  async function startVoice() {
    if (voicePhaseRef.current === VoicePhase.PREPARING) {
      stopVoice(false);
      setVoiceMessage("已取消，点击按钮可重新开始。");
      return;
    }
    if (voicePhaseRef.current === VoicePhase.LISTENING) {
      stopVoice(true);
      return;
    }
    if (voicePhaseRef.current !== VoicePhase.IDLE) {
      return;
    }
    finishedRef.current = false;
    partialTextRef.current = "";
    moveVoice(VoiceEvent.START);
    setVoiceMessage("正在准备语音识别，请看到“正在听”后再说话。");
    try {
      const runtimeMode = isLocalNetworkMode(networkStatus) ? "local" : "cloud";
      markNetworkActivity("upload");
      const ws = new WebSocket(websocketUrl(`/api/audio/asr/realtime?mode=${runtimeMode}`));
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => {
        setVoiceMessage("正在准备识别服务与麦克风...");
      };
      ws.onmessage = (event) => {
        markNetworkActivity("download");
        let data;
        try {
          data = JSON.parse(event.data || "{}");
        } catch {
          return;
        }
        if (data.type === "preparing") {
          setVoiceMessage(data.message || "正在准备识别服务与麦克风...");
          return;
        }
        if (data.type === "ready") {
          if (voicePhaseRef.current !== VoicePhase.PREPARING) {
            return;
          }
          moveVoice(VoiceEvent.READY);
          try {
            navigator.vibrate?.([28, 35, 28]);
          } catch {
            // Vibration feedback is optional.
          }
          setVoiceMessage(data.offline ? "本地识别正在听，请自然说话。" : "正在听，请自然说话。");
          return;
        }
        if (data.type === "error") {
          setVoiceMessage(data.message || "实时语音识别暂不可用。");
          notify(data.message || "实时语音识别暂不可用");
          stopVoice(false);
          return;
        }
        if (data.type === "transcript" && data.text) {
          if (![VoicePhase.LISTENING, VoicePhase.TRANSCRIBING].includes(voicePhaseRef.current)) {
            return;
          }
          partialTextRef.current = data.text;
          setVoiceMessage(data.final ? `识别完成：${data.text}` : `识别中：${data.text}`);
          if (data.final) {
            finishVoice(data.text);
          }
        }
      };
      ws.onerror = () => {
        const message = "实时语音识别连接失败，请检查外设语音服务。";
        setVoiceMessage(message);
        notify(message);
        stopVoice(false);
      };
      ws.onclose = () => {
        if (voicePhaseRef.current !== VoicePhase.IDLE && !finishedRef.current) {
          moveVoice(VoiceEvent.FAIL);
        }
      };
    } catch (error) {
      const message = error?.message || "外设麦克风启动失败，请检查设备连接。";
      setVoiceMessage(message);
      notify(message);
      stopVoice(false);
    }
  }

  function finishVoice(text) {
    if (finishedRef.current) {
      return;
    }
    finishedRef.current = true;
    stopVoice(false);
    const content = (text || partialTextRef.current || "").trim();
    if (content) {
      setVoiceMessage("语音已发送。");
      send(content);
      return;
    }
    setVoiceMessage("未识别到有效语音，请再试一次。");
  }

  function stopVoice(commit = true) {
    window.clearTimeout(finishTimerRef.current);
    const ws = wsRef.current;
    if (commit && voicePhaseRef.current === VoicePhase.LISTENING && ws?.readyState === WebSocket.OPEN) {
      moveVoice(VoiceEvent.STOP);
      markNetworkActivity("upload");
      ws.send(JSON.stringify({ type: "stop" }));
      setVoiceMessage("正在生成语音文字...");
      finishTimerRef.current = window.setTimeout(() => finishVoice(partialTextRef.current), 1800);
    } else if (ws && ws.readyState <= WebSocket.OPEN) {
      ws.close();
    }
    if (!commit || voicePhaseRef.current === VoicePhase.PREPARING) {
      moveVoice(VoiceEvent.CANCEL);
    }
    wsRef.current = null;
  }

  function moveVoice(event) {
    const next = nextVoicePhase(voicePhaseRef.current, event);
    voicePhaseRef.current = next;
    setVoicePhase(next);
  }

  function reset() {
    stopVoice(false);
    window.speechSynthesis?.cancel();
    setActiveProfile(null);
    profileRef.current = null;
    setVitalsSummary("");
    setMessages(initialMessages(null, history));
    setVoiceMessage("点击按钮开始语音问询。");
    waitingForVitalsRef.current = false;
    try {
      window.sessionStorage.removeItem(chatDraftKey);
      window.sessionStorage.removeItem(vitalsAwaitingKey);
    } catch {
      // sessionStorage is optional.
    }
  }

  function handleVoicePress() {
    try {
      navigator.vibrate?.(listening ? [24, 36, 24] : 36);
    } catch {
      // Vibration feedback is optional.
    }
    startVoice();
  }

  return (
    <section className="inquiry-chat-step voice-only" aria-label="AI 对话问询">
      <section className="chat-main-panel">
        <div className="chat-title-row">
          <span className="chat-assistant-motion" aria-hidden="true">
            <Bot size={26} />
          </span>
          <div>
            <h2>{activeProfile?.name ? `AI问询 · ${activeProfile.name}` : "AI问询 · 身份确认"}</h2>
          </div>
          <div className="chat-icon-actions">
            <button type="button" className="chat-speak-button icon-only" onClick={() => playReply(lastAssistantMessage(messages))} aria-label="重播最近回复">
              <Volume2 size={21} aria-hidden="true" />
            </button>
            <button type="button" className="chat-speak-button icon-only" onClick={reset} aria-label="重新对话">
              <RotateCcw size={21} aria-hidden="true" />
            </button>
          </div>
        </div>

        <div className="chat-thread" aria-live="polite">
          {messages.map((message, index) => (
            <article key={message.id || `${message.role}-${index}`} className={`chat-bubble ${message.role} ${message.streaming ? "streaming" : ""}`}>
              <p>{message.content || "正在生成回复..."}</p>
              {message.source ? <small>{aiSourceLabel(message.source)}</small> : null}
            </article>
          ))}
          {sending ? (
            <article className="chat-bubble assistant thinking">
              <StrokeDrawIcon icon={Bot} size={20} strokeWidth={2} mode="yoyo" />
              <p>正在整理你的信息...</p>
            </article>
          ) : null}
          <span ref={bottomRef} />
        </div>

        <div className="chat-voice-bar">
          <button
            className={`voice-chat-button compact ${preparingVoice ? "preparing" : listening ? "listening" : transcribingVoice || sending ? "processing" : ""}`}
            type="button"
            onClick={handleVoicePress}
            disabled={sending || transcribingVoice}
            aria-pressed={listening}
          >
            {listening ? (
              <StrokeDrawIcon icon={Mic} size={23} strokeWidth={2.2} mode="yoyo" />
            ) : preparingVoice ? (
              <LoaderCircle className="voice-preparing-spinner" size={23} aria-hidden="true" />
            ) : (
              <Mic size={23} aria-hidden="true" />
            )}
            {sending
              ? "AI 正在整理"
              : transcribingVoice
                ? "正在识别"
                : preparingVoice
                  ? "正在准备 · 点击取消"
                  : listening
                    ? "正在听 · 点击发送"
                    : "点击开始说话"}
          </button>
          <div className={`voice-status chat-voice-status ${preparingVoice ? "preparing" : listening ? "listening" : transcribingVoice || sending ? "processing" : ""}`} aria-live="polite">
            {voiceMessage}
          </div>
        </div>
      </section>
    </section>
  );
}

function websocketUrl(path) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}${path}`;
}
