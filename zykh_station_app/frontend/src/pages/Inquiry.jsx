import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  BadgeCheck,
  CircleHelp,
  Clock3,
  Droplets,
  HeartPulse,
  Pill,
  ScanFace,
  ShieldAlert,
  Thermometer,
  UserRound
} from "lucide-react";
import {
  attachInquiryVitals,
  confirmInquiryTreatment,
  createInquirySession,
  loadInquirySession,
  reviseInquiryInformation,
  sendInquiryTurn
} from "../api/inquiry.js";
import { stopAudioPlayback } from "../api/audio.js";
import { loadServiceUsers } from "../api/records.js";
import { InquiryChatStep } from "../components/InquiryChatStep.jsx";
import { InquiryIdentityGate } from "../components/InquiryIdentityGate.jsx";
import { InquiryInformationReview } from "../components/InquiryInformationReview.jsx";
import { InquiryResultStep } from "../components/InquiryResultStep.jsx";
import { activateIdentity, useFaceIdentity } from "../hooks/useFaceIdentity.js";
import { chiefComplaint } from "../utils/inquiryFacts.js";
import {
  clearInquirySession,
  INQUIRY_BACKEND_SESSION_KEY,
  INQUIRY_DRAFT_KEY
} from "../utils/inquirySession.js";
import { Vitals } from "./Vitals.jsx";
import "../styles/inquiry-actions.css";

function readJson(key) {
  try {
    const raw = window.sessionStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function normalizeUser(user) {
  if (!user) return null;
  return {
    id: user.id || "",
    name: user.name || "待确认",
    age: Number(user.age || 0),
    role: user.status || "家庭成员",
    conditions: user.profile || user.conditions || "待补充",
    allergies: user.allergies || "待补充",
    note: user.note || "请通过语音补充基础病、过敏禁忌和近期用药。"
  };
}

export function Inquiry({ notify, onNavigate, networkStatus }) {
  const draft = readJson(INQUIRY_DRAFT_KEY);
  const restoredSessionId = window.sessionStorage.getItem(INQUIRY_BACKEND_SESSION_KEY) || "";
  const [serviceUsers, setServiceUsers] = useState([]);
  const [selectedUserId, setSelectedUserId] = useState(draft?.selectedUserId || "");
  const [identityConfirmed, setIdentityConfirmed] = useState(Boolean(draft?.identityConfirmed));
  const [guestUser, setGuestUser] = useState(draft?.guestUser || null);
  const [session, setSession] = useState(null);
  const [sessionId, setSessionId] = useState(restoredSessionId);
  const [sending, setSending] = useState(false);
  const [openingTreatment, setOpeningTreatment] = useState(false);
  const [treatmentAction, setTreatmentAction] = useState(null);
  const [manualReviewOpen, setManualReviewOpen] = useState(false);
  const [resultConfirmed, setResultConfirmed] = useState(false);
  const [revisingResult, setRevisingResult] = useState(false);
  const [savingReview, setSavingReview] = useState(false);
  const [vitalsFlow, setVitalsFlow] = useState("chat");
  const [attachingVitals, setAttachingVitals] = useState(false);
  const creatingRef = useRef(false);
  const mountedRef = useRef(false);
  const openingTreatmentRef = useRef(false);
  const vitalsLaunchTimerRef = useRef(null);
  const launchedVitalsRequestRef = useRef("");
  const {
    identity: faceIdentity,
    status: faceIdentityStatus,
    identify: identifyFace,
    clear: clearFaceIdentity
  } = useFaceIdentity({ auto: false, activateOnMatch: false });

  const selectedUser = useMemo(
    () => normalizeUser(serviceUsers.find((user) => user.id === selectedUserId))
      || (identityConfirmed ? normalizeUser(guestUser || faceIdentity) : null),
    [faceIdentity, guestUser, identityConfirmed, selectedUserId, serviceUsers]
  );
  const candidateUser = identityConfirmed ? null : normalizeUser(faceIdentity);
  const displayedUser = selectedUser || candidateUser || (session ? {
    id: session.user_id,
    name: session.user_name,
    age: session.user_age,
    role: session.user_id ? "已登记" : "访客",
    conditions: session.user_profile || "待补充",
    allergies: session.user_allergies || "待补充",
    note: "请通过语音继续补充本次情况"
  } : null);
  const identityPresentation = displayedUser && identityConfirmed
    ? { icon: BadgeCheck, tone: "matched", label: `已确认使用人：${displayedUser.name}` }
    : candidateUser
      ? { icon: BadgeCheck, tone: "candidate", label: `识别到使用人：${candidateUser.name}` }
      : faceIdentityStatus === "identifying"
        ? { icon: ScanFace, tone: "identifying", label: "正在确认使用人" }
        : { icon: CircleHelp, tone: "pending", label: "使用人尚未确认" };
  const IdentityIcon = identityPresentation.icon;
  const contextSummary = useMemo(() => {
    const extracted = session?.extracted_information || {};
    const observations = (extracted.observations || [])
      .filter((item) => item?.status === "present");
    const dimensions = (extracted.symptom_dimensions || [])
      .map((value) => symptomDimensionLabel(value))
      .filter(Boolean);
    const vitals = session?.vitals || {};
    const temperature = Number(vitals.temperature) > 0 ? `${Number(vitals.temperature).toFixed(1)}℃` : "待测";
    const heartRate = Number(vitals.heart_rate) > 0 ? `${Number(vitals.heart_rate)}` : "待测";
    const spo2 = Number(vitals.spo2) > 0 ? `${Number(vitals.spo2)}%` : "待测";
    const allergy = extracted.allergy_or_contraindication || displayedUser?.allergies || "";
    const medicineText = extracted.used_medicines === "未使用"
      ? "本次未用药"
      : extracted.used_medicines === "已使用"
        ? "本次已用药"
        : extracted.used_medicines || "尚未确认";
    return {
      complaint: chiefComplaint({
        ...extracted,
        symptom_dimensions: dimensions
      }).replace("尚未说明", "等待描述"),
      duration: extracted.duration || "尚未确认",
      medicine: medicineText,
      allergy: allergy || "尚未确认",
      temperature,
      heartRate,
      spo2
    };
  }, [displayedUser, session]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      window.clearTimeout(vitalsLaunchTimerRef.current);
      stopAudioPlayback().catch(() => null);
    };
  }, []);

  useEffect(() => {
    refreshUsers();
    if (restoredSessionId) {
      loadInquirySession(restoredSessionId)
        .then((data) => {
          setSession(data);
          setIdentityConfirmed(true);
          setSelectedUserId(data.user_id || "");
          if (!data.user_id) setGuestUser({ name: data.user_name, status: "访客" });
        })
        .catch(() => {
          setSessionId("");
          window.sessionStorage.removeItem(INQUIRY_BACKEND_SESSION_KEY);
        });
    } else if (!identityConfirmed) {
      clearFaceIdentity();
      window.setTimeout(() => identifyFace({ force: true }).catch(() => null), 180);
    }
  }, []);

  useEffect(() => {
    try {
      window.sessionStorage.setItem(
        INQUIRY_DRAFT_KEY,
        JSON.stringify({ selectedUserId, identityConfirmed, guestUser })
      );
    } catch {
      // Session storage is optional.
    }
  }, [guestUser, identityConfirmed, selectedUserId]);

  useEffect(() => {
    if (!identityConfirmed || sessionId || creatingRef.current) return;
    const creationToken = Symbol("inquiry-session-creation");
    creatingRef.current = creationToken;
    createInquirySession({
      service_user_id: selectedUserId,
      guest_name: guestUser?.name || "访客"
    })
      .then((data) => {
        if (!mountedRef.current || creatingRef.current !== creationToken) return;
        setSession(data);
        setSessionId(data.session_id);
        window.sessionStorage.setItem(INQUIRY_BACKEND_SESSION_KEY, data.session_id);
      })
      .catch((error) => {
        if (!mountedRef.current || creatingRef.current !== creationToken) return;
        notify(error.message || "问询会话创建失败，请重试");
        setIdentityConfirmed(false);
        window.setTimeout(() => identifyFace({ force: true }).catch(() => null), 180);
      })
      .finally(() => {
        if (creatingRef.current === creationToken) creatingRef.current = false;
      });
  }, [guestUser, identityConfirmed, selectedUserId, sessionId]);

  function refreshUsers() {
    return loadServiceUsers().then((data) => setServiceUsers(data.users || [])).catch(() => setServiceUsers([]));
  }

  function confirmIdentity() {
    if (!faceIdentity?.id) return;
    setSelectedUserId(faceIdentity.id);
    setIdentityConfirmed(true);
    setGuestUser(null);
    activateIdentity(faceIdentity);
    notify(`已确认使用人：${faceIdentity.name}`);
  }

  function retryIdentity() {
    setSelectedUserId("");
    setIdentityConfirmed(false);
    setGuestUser(null);
    clearFaceIdentity();
    window.setTimeout(() => identifyFace({ force: true }).catch(() => null), 180);
  }

  function confirmGuestInquiry() {
    const visitor = { id: "", name: "访客", age: 0, profile: "身份未登记", allergies: "待问询确认", status: "访客" };
    clearFaceIdentity();
    setGuestUser(visitor);
    setSelectedUserId("");
    setIdentityConfirmed(true);
    activateIdentity(visitor);
    notify("已以访客身份开始问询");
  }

  async function handleTurn(transcript) {
    if (!sessionId || sending) return;
    setSending(true);
    try {
      const data = await sendInquiryTurn(sessionId, transcript);
      handleSessionUpdate(data);
    } catch (error) {
      notify(error.message || "问询暂不可用，请重试");
    } finally {
      setSending(false);
    }
  }

  function handleSessionUpdate(data) {
    setSession(data);
    if (data.stage === "result") {
      setResultConfirmed(false);
      setRevisingResult(false);
      setManualReviewOpen(false);
    }
    if (data.next_action !== "measure_vitals") {
      setVitalsFlow("chat");
      launchedVitalsRequestRef.current = "";
    }
  }

  const handleReplyPlaybackStart = useCallback(() => {
    if (!session || session.next_action !== "measure_vitals" || attachingVitals) return;
    const requestKey = `${session.session_id}:${session.updated_at}`;
    if (launchedVitalsRequestRef.current === requestKey) return;
    launchedVitalsRequestRef.current = requestKey;
    window.clearTimeout(vitalsLaunchTimerRef.current);
    vitalsLaunchTimerRef.current = window.setTimeout(() => {
      if (mountedRef.current) setVitalsFlow("measuring");
    }, 3000);
  }, [attachingVitals, session]);

  const handleVitalsComplete = useCallback(async (vitals) => {
    if (!sessionId || attachingVitals) return;
    setAttachingVitals(true);
    try {
      const updated = await attachInquiryVitals(sessionId, {
        status: "complete",
        temperature: vitals.temperature,
        heart_rate: vitals.heart_rate,
        spo2: vitals.spo2,
        systolic_pressure: vitals.systolic_pressure || null,
        diastolic_pressure: vitals.diastolic_pressure || null,
        respiratory_rate: vitals.respiratory_rate || null,
        hrv_sdnn: vitals.hrv_sdnn || null,
        hrv_rmssd: vitals.hrv_rmssd || null,
        measured_at: vitals.measured_at || new Date().toISOString()
      });
      setVitalsFlow("chat");
      handleSessionUpdate(updated);
    } catch (error) {
      notify(error.message || "体征信息未能写入本次问询");
    } finally {
      setAttachingVitals(false);
    }
  }, [attachingVitals, notify, sessionId]);

  const handleVitalsExit = useCallback(async (outcome) => {
    if (!sessionId || attachingVitals) return;
    setAttachingVitals(true);
    try {
      const updated = await attachInquiryVitals(sessionId, {
        status: outcome?.status === "failed" ? "failed" : "cancelled",
        error_message: outcome?.error_message || "",
        measured_at: new Date().toISOString()
      });
      setVitalsFlow("chat");
      handleSessionUpdate(updated);
    } catch (error) {
      setVitalsFlow("chat");
      notify(error.message || "已返回问询，体征状态暂未写入");
    } finally {
      setAttachingVitals(false);
    }
  }, [attachingVitals, notify, sessionId]);

  const handleTreatmentConfirm = useCallback(async (optionId) => {
    if (!sessionId || openingTreatmentRef.current) return;
    openingTreatmentRef.current = true;
    setOpeningTreatment(true);
    setTreatmentAction(null);
    setManualReviewOpen(false);
    setRevisingResult(false);
    try {
      let expectedItemIndex = Number(session?.action_progress_index || 0);
      while (mountedRef.current) {
        const data = await confirmInquiryTreatment(sessionId, optionId, expectedItemIndex);
        setTreatmentAction(data);
        setSession(data.session);
        notify(data.message || "方案对应药柜已处理");
        if (data.status !== "opening") break;
        expectedItemIndex = Number(data.completed_count || 0);
        await new Promise((resolve) => window.setTimeout(resolve, 1800));
      }
    } catch (error) {
      setTreatmentAction({ status: "failed", message: error.message || "开柜未完成，请联系现场协助人员" });
      notify(error.message || "开柜未完成，请联系现场协助人员");
      loadInquirySession(sessionId)
        .then((latest) => {
          setSession(latest);
          if (latest.action_status === "ready") setTreatmentAction(null);
        })
        .catch(() => null);
    } finally {
      openingTreatmentRef.current = false;
      setOpeningTreatment(false);
    }
  }, [notify, session?.action_progress_index, sessionId]);

  function resetFlow() {
    creatingRef.current = false;
    clearInquirySession();
    setSession(null);
    setSessionId("");
    setSelectedUserId("");
    setIdentityConfirmed(false);
    setGuestUser(null);
    setOpeningTreatment(false);
    openingTreatmentRef.current = false;
    setTreatmentAction(null);
    setVitalsFlow("chat");
    setAttachingVitals(false);
    launchedVitalsRequestRef.current = "";
    window.clearTimeout(vitalsLaunchTimerRef.current);
    stopAudioPlayback().catch(() => null);
    clearFaceIdentity();
    window.setTimeout(() => identifyFace({ force: true }).catch(() => null), 220);
  }

  const resultReady = session?.stage === "result";
  const showResult = session?.stage === "escalated" || (resultReady && resultConfirmed);
  const showReview = Boolean(
    session && (manualReviewOpen || (resultReady && !resultConfirmed && !revisingResult))
  );

  async function confirmInformationReview(information, changed = false) {
    if (savingReview) return;
    setManualReviewOpen(false);
    if (changed && sessionId) {
      setSavingReview(true);
      try {
        const updated = await reviseInquiryInformation(sessionId, {
          ...information,
          finalize: resultReady
        });
        handleSessionUpdate(updated);
        setRevisingResult(false);
        setResultConfirmed(updated.stage === "result");
        if (updated.next_action !== "measure_vitals" && updated.stage !== "result") {
          notify("修正内容已保存，请继续问询");
        }
      } catch (error) {
        setManualReviewOpen(true);
        notify(error.message || "问询信息保存失败，请重试");
      } finally {
        setSavingReview(false);
      }
      return;
    }
    if (resultReady) {
      setResultConfirmed(true);
      setRevisingResult(false);
    } else {
      notify("已确认当前问询信息，可以继续补充");
    }
  }

  function continueInquiryFromReview() {
    setManualReviewOpen(false);
    if (resultReady) setRevisingResult(true);
  }

  const vitalsSubflow = vitalsFlow !== "chat";

  return (
    <main className={`inquiry-page conversation-layout ${vitalsSubflow ? "vitals-subflow" : ""}`} id="main-content">
      {!vitalsSubflow ? <aside className="inquiry-context-panel" aria-label="使用人信息">
        <section className="inquiry-user-card dynamic">
          <div className="context-heading user-context-heading">
            <UserRound size={26} aria-hidden="true" />
            <div className="user-context-copy"><span>使用人</span><h2>{displayedUser?.name || "等待确认"}</h2></div>
            <span className={`identity-confirmation-icon ${identityPresentation.tone}`} role="img" aria-label={identityPresentation.label} title={identityPresentation.label}>
              <IdentityIcon size={24} aria-hidden="true" />
            </span>
          </div>
          <div className="context-profile-summary">
            <div className="context-profile-tags">
              <span>{displayedUser?.age ? `${displayedUser.age}岁` : "年龄待补充"}</span>
              <span>{displayedUser?.role || "身份待确认"}</span>
            </div>
            <p><HeartPulse size={18} aria-hidden="true" />{displayedUser?.conditions || "健康背景待补充"}</p>
          </div>
          <div className="inquiry-live-summary">
            <header><span>问询信息</span></header>
            <div className="inquiry-fact-list">
              <article className="inquiry-chief-fact"><UserRound size={21} /><span><small>主要不适</small><strong>{contextSummary.complaint}</strong></span></article>
              <div className="inquiry-fact-pair">
                <article><Clock3 size={20} /><span><small>持续时间</small><strong>{contextSummary.duration}</strong></span></article>
                <article><Pill size={20} /><span><small>本次用药</small><strong>{contextSummary.medicine}</strong></span></article>
              </div>
              <article className="inquiry-allergy-fact"><ShieldAlert size={20} /><span><small>过敏或禁忌</small><strong>{contextSummary.allergy}</strong></span></article>
            </div>
            <section className="inquiry-core-vitals" aria-label="核心体征">
              <header><Thermometer size={19} aria-hidden="true" /><strong>体征信息</strong></header>
              <div>
                <span><HeartPulse size={18} /><small>心率</small><strong>{contextSummary.heartRate}</strong></span>
                <span><Droplets size={18} /><small>血氧</small><strong>{contextSummary.spo2}</strong></span>
                <span><Activity size={18} /><small>额温</small><strong>{contextSummary.temperature}</strong></span>
              </div>
            </section>
          </div>
        </section>
      </aside> : null}

      <section className={`inquiry-flow-card chat-only ${vitalsSubflow ? "vitals-tool-host" : ""}`} aria-label="AI 应急问询流程">
        {vitalsFlow === "measuring" ? (
          <Vitals
            embedded
            notify={notify}
            onComplete={handleVitalsComplete}
            onExit={handleVitalsExit}
          />
        ) : !identityConfirmed ? (
          <InquiryIdentityGate candidate={candidateUser} status={faceIdentityStatus} onConfirm={confirmIdentity} onRetry={retryIdentity} onRequestGuest={confirmGuestInquiry} />
        ) : showReview ? (
          <InquiryInformationReview
            session={session}
            ready={resultReady}
            saving={savingReview}
            onConfirm={confirmInformationReview}
            onContinue={continueInquiryFromReview}
            networkStatus={networkStatus}
          />
        ) : showResult ? (
          <InquiryResultStep
            result={session}
            opening={openingTreatment}
            actionResult={treatmentAction}
            onConfirmTreatment={handleTreatmentConfirm}
            onRestart={resetFlow}
            onHome={() => onNavigate("home")}
            networkStatus={networkStatus}
          />
        ) : session ? (
          <InquiryChatStep
            session={session}
            sending={sending}
            notify={notify}
            onSend={handleTurn}
            onReset={resetFlow}
            onReview={() => setManualReviewOpen(true)}
            onReplyPlaybackStart={handleReplyPlaybackStart}
            networkStatus={networkStatus}
          />
        ) : (
          <div className="inquiry-session-loading" role="status">正在建立本次问询...</div>
        )}
      </section>
    </main>
  );
}

const symptomDimensionLabels = {
  "感冒鼻部症状": "鼻塞流涕",
  "发热全身不适": "头痛或全身不适",
  "咳嗽咳痰": "咳嗽咳痰",
  "咽喉口腔不适": "咽喉或口腔不适",
  "恶心暑湿": "头晕恶心或暑热不适",
  "腹泻肠道不适": "腹泻肠道不适",
  "便秘": "排便困难",
  "胃酸胃部不适": "反酸或胃部不适",
  "过敏瘙痒": "皮肤过敏瘙痒",
  "轻微外伤": "轻微外伤",
  "皮肤真菌不适": "皮肤真菌不适",
  "肌肉关节疼痛": "肌肉关节疼痛",
  "干眼不适": "眼干眼涩",
  "鼻炎过敏": "鼻炎过敏",
  "营养补充": "营养补充",
  "慢病既往用药": "慢病既往用药"
};

function symptomDimensionLabel(value) {
  const normalized = String(value || "").trim();
  return symptomDimensionLabels[normalized] || normalized;
}
