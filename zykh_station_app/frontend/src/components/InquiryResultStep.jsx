import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  CircleCheckBig,
  Cpu,
  DoorOpen,
  Home,
  LoaderCircle,
  MessageCircle,
  Pill,
  RotateCcw,
  ShieldCheck,
  Sparkles,
  X
} from "lucide-react";
import { RiskBadge } from "./RiskBadge.jsx";
import { aiSourcePresentation } from "../utils/ai.js";
import { speakText, stopAudioPlayback } from "../api/audio.js";
import { isLocalNetworkMode } from "../utils/network.js";
import { buildActionSpeech, buildRecommendationSpeech } from "../utils/inquirySpeech.js";

const riskLabels = {
  low: "低风险",
  medium: "中风险",
  high: "高风险",
  emergency: "紧急风险"
};

const terminalStatuses = new Set(["complete", "partial", "failed"]);

export function InquiryResultStep({
  result,
  opening,
  actionResult,
  onConfirmTreatment,
  onRestart,
  onHome,
  networkStatus
}) {
  const options = result?.treatment_options || [];
  const [selectedOptionId, setSelectedOptionId] = useState(result?.selected_option_id || options[0]?.option_id || "");
  const [countdown, setCountdown] = useState(null);
  const highRisk = ["high", "emergency"].includes(result?.risk_level);
  const requiresEscalation = highRisk || result?.next_action === "escalate";
  const actionStatus = actionResult?.status || result?.action_status || "idle";
  const actionMessage = actionResult?.message || result?.action_message || "";
  const canProceed = Boolean(result?.can_view_medicines && options.length && !highRisk);
  const actionFinished = terminalStatuses.has(actionStatus);
  const activelyOpening = opening;
  const resumePending = !opening && actionStatus === "opening";
  const selectedOption = useMemo(
    () => options.find((option) => option.option_id === selectedOptionId) || options[0],
    [options, selectedOptionId]
  );
  const completedCount = Number(actionResult?.completed_count ?? result?.action_progress_index ?? 0);
  const reportedTotal = Number(actionResult?.total_count || result?.action_total_items || 0);
  const totalCount = reportedTotal > 0 ? reportedTotal : Number(selectedOption?.medicines?.length || 0);
  const remainingCount = Math.max(totalCount - completedCount, 1);
  const nextMedicine = actionResult?.next_medicine || selectedOption?.medicines?.[completedCount] || null;
  const requiresExistingDirection = Boolean(
    selectedOption?.medicines?.some((medicine) => medicine.requires_existing_direction)
  );
  const lastRecommendationKeyRef = useRef("");
  const spokenActionKeysRef = useRef(new Set());
  const playbackGenerationRef = useRef(0);

  useEffect(() => {
    if (!result?.session_id) return;
    const key = `recommendation:${result.session_id}:${selectedOption?.option_id || "none"}`;
    if (lastRecommendationKeyRef.current === key) return;
    lastRecommendationKeyRef.current = key;
    playResultSpeech(buildRecommendationSpeech(result, selectedOption), networkStatus, playbackGenerationRef);
  }, [networkStatus, result, selectedOption]);

  useEffect(() => {
    if (!actionFinished || !actionMessage) return;
    const key = `action:${result?.session_id}:${actionStatus}`;
    if (spokenActionKeysRef.current.has(key)) return;
    spokenActionKeysRef.current.add(key);
    playResultSpeech(buildActionSpeech(actionMessage), networkStatus, playbackGenerationRef);
  }, [actionFinished, actionMessage, actionStatus, networkStatus, result?.session_id]);

  useEffect(() => () => {
    playbackGenerationRef.current += 1;
    window.speechSynthesis?.cancel();
    stopAudioPlayback().catch(() => null);
  }, []);

  useEffect(() => {
    if (!options.some((option) => option.option_id === selectedOptionId)) {
      setSelectedOptionId(options[0]?.option_id || "");
    }
  }, [options, selectedOptionId]);

  useEffect(() => {
    if (countdown === null) return undefined;
    if (countdown <= 0) {
      setCountdown(null);
      onConfirmTreatment(selectedOptionId);
      return undefined;
    }
    const timer = window.setTimeout(() => setCountdown((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [countdown, onConfirmTreatment, selectedOptionId]);

  function beginConfirmation() {
    if (!selectedOptionId || activelyOpening || actionFinished) return;
    const cabinetText = selectedOption?.medicines?.map((medicine) => `${medicine.slot}号柜`).join("、") || "对应药柜";
    playResultSpeech(
      `方案已确认，三秒后将依次打开${cabinetText}，请准备取药。`,
      networkStatus,
      playbackGenerationRef
    );
    setCountdown(3);
  }

  return (
    <section className="inquiry-treatment-result">
      <header className="treatment-result-header">
        <span className={`treatment-risk-icon ${result?.risk_level === "low" ? "low" : "warn"}`} aria-hidden="true">
          {result?.risk_level === "low" ? <ShieldCheck size={38} /> : <AlertTriangle size={38} />}
        </span>
        <div>
          <h2>{requiresEscalation ? "请优先联系专业人员" : canProceed ? "请选择一个方案" : "本次护理建议"}</h2>
        </div>
        <div className="treatment-result-meta">
          <RiskBadge level={result?.risk_level} label={riskLabels[result?.risk_level] || "待核验"} />
          <ResultSource source={result?.source} />
        </div>
      </header>

      {canProceed ? (
        <div className={`treatment-option-grid count-${Math.min(options.length, 2)}`} role="radiogroup" aria-label="用药方案">
          {options.slice(0, 2).map((option, optionIndex) => {
            const selected = option.option_id === selectedOptionId;
            return (
              <label className={`treatment-option-card ${optionIndex === 0 ? "recommended" : "alternative"} ${selected ? "selected" : ""}`} key={option.option_id}>
                <input
                  type="radio"
                  name="treatment-option"
                  value={option.option_id}
                  checked={selected}
                  disabled={activelyOpening || resumePending || countdown !== null || actionFinished}
                  onChange={() => setSelectedOptionId(option.option_id)}
                />
                <span className="option-choice-mark">{selected ? <Check size={18} /> : optionIndex + 1}</span>
                <span className="option-heading">
                  <strong>{optionIndex === 0 ? "推荐方案" : "备选方案"}</strong>
                  {optionIndex === 0 ? <em>优先推荐</em> : null}
                  <small>{optionDescription(option, optionIndex)}</small>
                </span>
                <span className="option-medicine-list">
                  {option.medicines.map((medicine) => (
                    <span className="option-medicine-row" key={medicine.id}>
                      <Pill size={18} aria-hidden="true" />
                      <span>
                        <strong>{medicine.name}</strong>
                        <small className={medicine.requires_existing_direction ? "direction-required" : ""}>
                          {medicine.recommended_usage || medicine.dosage || (medicine.requires_existing_direction ? "按既往医嘱核对" : medicine.role)}
                        </small>
                      </span>
                      <em>{medicine.slot}号柜</em>
                    </span>
                  ))}
                </span>
              </label>
            );
          })}
        </div>
      ) : requiresEscalation ? (
        <div className="treatment-escalation-panel">
          <AlertTriangle size={50} aria-hidden="true" />
          <strong>{result?.reply || "本次不展示候选方案"}</strong>
          <span>请联系医生、家人或现场协助人员，不要自行新增用药。</span>
        </div>
      ) : (
        <div className="treatment-guidance-panel">
          <ShieldCheck size={56} aria-hidden="true" />
          <strong>{result?.reply || "目前更适合先做基础护理和观察。"}</strong>
          <span>情况发生变化时，可以重新开始问询。</span>
        </div>
      )}

      <div className="treatment-result-footer-row">
        {canProceed && !actionFinished ? (
          <div className={`treatment-confirm-bar ${requiresExistingDirection ? "with-notice" : "simple"}`}>
            {requiresExistingDirection ? (
              <div className="treatment-confirm-notice">
                <ShieldCheck size={20} />
                <span>仅限本人既往医嘱中已经使用的药品。</span>
              </div>
            ) : null}
            {countdown !== null ? (
              <div className="treatment-countdown" role="status">
                <strong>{countdown}</strong>
                <span>秒后{resumePending ? "继续" : "开始"}打开 {resumePending ? remainingCount : totalCount} 个对应药柜</span>
                <button type="button" onClick={() => setCountdown(null)} aria-label="取消开柜倒计时"><X size={20} /></button>
              </div>
            ) : activelyOpening ? (
              <div className="treatment-opening-progress" role="status" aria-live="polite">
                <span><LoaderCircle className="spin" size={22} /></span>
                <div>
                  <strong>正在逐柜处理 {Math.min(completedCount + 1, totalCount)}/{totalCount}</strong>
                  <small>{nextMedicine ? `当前：${nextMedicine.slot}号柜 · ${nextMedicine.name}` : "正在确认柜门状态"}</small>
                </div>
                <em>{completedCount}/{totalCount}</em>
              </div>
            ) : (
              <button
                className="treatment-open-button"
                type="button"
                disabled={activelyOpening}
                onClick={beginConfirmation}
              >
                <DoorOpen size={23} />
                {resumePending ? "继续打开下一柜" : "确认方案并逐柜打开"}
              </button>
            )}
          </div>
        ) : null}

        {actionFinished ? (
          <div className={`treatment-action-result ${actionStatus}`} role="status">
            {actionStatus === "complete" ? <CircleCheckBig size={26} /> : <AlertTriangle size={26} />}
            <strong>{actionMessage}</strong>
          </div>
        ) : null}

        <footer className="treatment-result-actions">
          <button className="compact-result-action" type="button" onClick={onRestart} aria-label="重新问询" title="重新问询"><RotateCcw size={23} /></button>
          <button className="compact-result-action" type="button" onClick={onHome} aria-label="返回首页" title="返回首页"><Home size={23} /></button>
        </footer>
      </div>
    </section>
  );
}

function ResultSource({ source }) {
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
      className={`result-source-icon ${presentation.kind}`}
      role="img"
      aria-label={presentation.label}
      title={presentation.label}
    >
      <Icon size={17} aria-hidden="true" />
    </span>
  );
}

function optionDescription(option, index) {
  if (option?.when) return option.when;
  const medicine = option?.medicines?.[0]?.name || "对应药品";
  return index === 0
    ? `${medicine}更贴近你这次描述的主要不适，可先对照药品说明。`
    : `${medicine}的侧重点不同，如果更符合你最明显的不适，可对照这一方案。`;
}

async function playResultSpeech(text, networkStatus, playbackGenerationRef) {
  if (!text) return;
  const generation = playbackGenerationRef.current + 1;
  playbackGenerationRef.current = generation;
  window.speechSynthesis?.cancel();
  await stopAudioPlayback().catch(() => null);
  if (generation !== playbackGenerationRef.current) return;
  try {
    await speakText(text, undefined, 1.12, isLocalNetworkMode(networkStatus) ? "offline" : "auto");
  } catch {
    if (generation === playbackGenerationRef.current) speakResultLocally(text);
  }
}

function speakResultLocally(text) {
  if (!window.speechSynthesis || typeof SpeechSynthesisUtterance === "undefined") return;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 1.08;
  window.speechSynthesis.speak(utterance);
}
