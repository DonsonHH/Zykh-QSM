import React, { useEffect, useRef, useState } from "react";
import {
  Activity,
  Check,
  Clock3,
  Droplets,
  HeartPulse,
  Keyboard,
  Pill,
  ShieldCheck,
  Thermometer,
  UserRound
} from "lucide-react";
import { speakText, stopAudioPlayback } from "../api/audio.js";
import { fullComplaint } from "../utils/inquiryFacts.js";
import { buildInformationReviewSpeech } from "../utils/inquirySpeech.js";

const AUTO_CONFIRM_SECONDS = 15;

export function InquiryInformationReview({
  session,
  ready,
  saving = false,
  onConfirm,
  onContinue
}) {
  const [remainingMs, setRemainingMs] = useState(ready ? AUTO_CONFIRM_SECONDS * 1000 : null);
  const [interacted, setInteracted] = useState(false);
  const [draft, setDraft] = useState(() => buildFacts(session?.extracted_information || {}));
  const confirmRef = useRef(onConfirm);
  const draftRef = useRef(draft);
  const initialRef = useRef(draft);
  const playbackGenerationRef = useRef(0);
  confirmRef.current = onConfirm;
  draftRef.current = draft;
  const extracted = session?.extracted_information || {};
  const vitals = session?.vitals || {};
  const autoActive = ready && !interacted && !saving;

  useEffect(() => {
    const facts = buildFacts(extracted);
    initialRef.current = facts;
    draftRef.current = facts;
    setDraft(facts);
    setInteracted(false);
  }, [session?.session_id, session?.updated_at]);

  useEffect(() => {
    if (!session?.session_id) return;
    const timer = window.setTimeout(() => {
      playReviewSpeech(
        buildInformationReviewSpeech(session),
        playbackGenerationRef
      );
    }, 180);
    return () => window.clearTimeout(timer);
  }, [session?.session_id]);

  useEffect(() => () => {
    playbackGenerationRef.current += 1;
    stopAudioPlayback().catch(() => null);
  }, []);

  useEffect(() => {
    if (!autoActive) {
      setRemainingMs(null);
      return undefined;
    }
    const deadline = performance.now() + AUTO_CONFIRM_SECONDS * 1000;
    setRemainingMs(AUTO_CONFIRM_SECONDS * 1000);
    const timer = window.setInterval(() => {
      const next = Math.max(0, deadline - performance.now());
      setRemainingMs(next);
      if (next === 0) {
        window.clearInterval(timer);
        confirmRef.current(toPayload(draftRef.current), false);
      }
    }, 100);
    return () => window.clearInterval(timer);
  }, [autoActive, session?.session_id]);

  const seconds = remainingMs === null ? null : Math.max(0, Math.ceil(remainingMs / 1000));

  return (
    <section className="inquiry-information-review" aria-label="问询信息核对">
      <header className="review-heading">
        <span className="review-heading-icon" aria-hidden="true"><ShieldCheck size={30} /></span>
        <div>
          <p>问询信息核对</p>
          <h2>{ready ? "请确认这些信息是否准确" : "这是目前已经整理的信息"}</h2>
        </div>
        {autoActive ? (
          <span className="review-countdown" role="timer" aria-label={`${seconds}秒后自动确认`}>
            <strong>{seconds}</strong><small>秒</small>
          </span>
        ) : null}
      </header>

      <div className={`review-auto-progress ${autoActive ? "active" : "manual"}`} aria-hidden="true">
        {autoActive ? <span /> : null}
      </div>

      <div className="review-person-row">
        <UserRound size={23} aria-hidden="true" />
        <strong>{session?.user_name || "访客"}</strong>
        {session?.user_age ? <span>{session.user_age}岁</span> : null}
        {session?.user_profile ? <span>{session.user_profile}</span> : null}
      </div>

      <div className="review-fact-grid">
        <ReviewFact icon={Activity} label="主要不适" field="complaint" value={draft.complaint} multiline onChange={updateDraft} onEdit={beginEdit} />
        <ReviewFact icon={Clock3} label="持续时间" field="duration" value={draft.duration} onChange={updateDraft} onEdit={beginEdit} />
        <ReviewFact icon={Pill} label="已经用药" field="usedMedicines" value={draft.usedMedicines} onChange={updateDraft} onEdit={beginEdit} />
        <ReviewFact icon={ShieldCheck} label="过敏与禁忌" field="allergy" value={draft.allergy} onChange={updateDraft} onEdit={beginEdit} />
      </div>

      <section className="review-vitals-row" aria-label="本次体征">
        <ReviewVital icon={HeartPulse} label="心率" value={metric(vitals.heart_rate, "次/分")} />
        <ReviewVital icon={Droplets} label="血氧" value={metric(vitals.spo2, "%")} />
        <ReviewVital icon={Thermometer} label="额温" value={temperature(vitals.temperature)} />
      </section>

      <footer className="review-actions">
        <div className="review-guidance"><Keyboard size={20} /><span>点按任意信息即可修改；开始编辑后不会自动确认。</span></div>
        <button type="button" className="secondary-action" onClick={onContinue} disabled={saving}>继续补充</button>
        <button type="button" className="primary-action" disabled={saving || !isComplete(draft)} onClick={() => onConfirm(toPayload(draft), isChanged(draft, initialRef.current))}>
          <Check size={21} />{saving ? "正在保存" : ready ? "确认信息并查看结果" : "确认当前信息"}
        </button>
      </footer>
    </section>
  );

  function beginEdit() {
    setInteracted(true);
  }

  function updateDraft(field, value) {
    setInteracted(true);
    setDraft((current) => ({ ...current, [field]: value }));
  }
}

async function playReviewSpeech(text, playbackGenerationRef) {
  if (!text) return;
  const generation = playbackGenerationRef.current + 1;
  playbackGenerationRef.current = generation;
  await stopAudioPlayback().catch(() => null);
  if (generation !== playbackGenerationRef.current) return;
  await speakText(text, undefined, 1.12, "auto").catch(() => null);
}

function ReviewFact({ icon: Icon, label, field, value, multiline = false, onChange, onEdit }) {
  const Control = multiline ? "textarea" : "input";
  return (
    <label className={`review-fact editable ${multiline ? "multiline" : ""}`} data-touch-editable>
      <Icon size={21} aria-hidden="true" />
      <span>
        <small>{label}</small>
        <Control
          type={multiline ? undefined : "text"}
          inputMode="text"
          value={value}
          rows={multiline ? 2 : undefined}
          onPointerDown={onEdit}
          onFocus={onEdit}
          onChange={(event) => onChange(field, event.target.value)}
          aria-label={`修改${label}`}
        />
      </span>
    </label>
  );
}

function ReviewVital({ icon: Icon, label, value }) {
  return (
    <span className={value === "尚未测量" ? "pending" : ""}>
      <Icon size={21} aria-hidden="true" />
      <small>{label}</small>
      <strong>{value}</strong>
    </span>
  );
}

function buildFacts(extracted) {
  return {
    complaint: fullComplaint(extracted),
    duration: extracted.duration || "尚未说明",
    usedMedicines: extracted.used_medicines || "尚未说明",
    allergy: extracted.allergy_or_contraindication || "尚未说明"
  };
}

function toPayload(facts) {
  return {
    main_complaint: facts.complaint.trim(),
    duration: facts.duration.trim(),
    used_medicines: facts.usedMedicines.trim(),
    allergy_or_contraindication: facts.allergy.trim()
  };
}

function isComplete(facts) {
  return Object.values(toPayload(facts)).every(Boolean);
}

function isChanged(current, initial) {
  return JSON.stringify(toPayload(current)) !== JSON.stringify(toPayload(initial));
}

function metric(value, unit) {
  const number = Number(value);
  return number > 0 ? `${number}${unit}` : "尚未测量";
}

function temperature(value) {
  const number = Number(value);
  return number > 0 ? `${number.toFixed(1)}℃` : "尚未测量";
}
