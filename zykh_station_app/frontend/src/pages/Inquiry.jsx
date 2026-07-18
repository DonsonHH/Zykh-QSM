import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BadgeCheck,
  CakeSlice,
  CircleHelp,
  HeartPulse,
  House,
  NotebookText,
  ScanFace,
  ShieldAlert,
  UserRound
} from "lucide-react";
import {
  attachInquiryVitals,
  confirmInquiryTreatment,
  createInquirySession,
  loadInquirySession,
  sendInquiryTurn
} from "../api/inquiry.js";
import { loadServiceUsers } from "../api/records.js";
import { InquiryChatStep } from "../components/InquiryChatStep.jsx";
import { InquiryIdentityGate } from "../components/InquiryIdentityGate.jsx";
import { InquiryResultStep } from "../components/InquiryResultStep.jsx";
import { activateIdentity, useFaceIdentity } from "../hooks/useFaceIdentity.js";
import {
  clearInquirySession,
  INQUIRY_BACKEND_SESSION_KEY,
  INQUIRY_DRAFT_KEY,
  INQUIRY_VITALS_AWAITING_KEY
} from "../utils/inquirySession.js";
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
  const creatingRef = useRef(false);
  const mountedRef = useRef(false);
  const openingTreatmentRef = useRef(false);
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

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
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

  useEffect(() => {
    if (!sessionId) return;
    const awaiting = window.sessionStorage.getItem(INQUIRY_VITALS_AWAITING_KEY);
    const vitals = readJson("zykh-latest-vitals");
    if (awaiting !== sessionId || !vitals || vitals.status !== "complete") return;
    window.sessionStorage.removeItem(INQUIRY_VITALS_AWAITING_KEY);
    attachInquiryVitals(sessionId, {
      temperature: vitals.temperature,
      heart_rate: vitals.heart_rate,
      spo2: vitals.spo2,
      systolic_pressure: vitals.systolic_pressure || null,
      diastolic_pressure: vitals.diastolic_pressure || null,
      respiratory_rate: vitals.respiratory_rate || null,
      hrv_sdnn: vitals.hrv_sdnn || null,
      hrv_rmssd: vitals.hrv_rmssd || null,
      measured_at: vitals.measured_at || new Date().toISOString()
    })
      .then(handleSessionUpdate)
      .catch((error) => notify(error.message || "体征信息未能写入本次问询"));
  }, [sessionId]);

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
    if (data.next_action === "measure_vitals") {
      window.sessionStorage.removeItem("zykh-latest-vitals");
      window.sessionStorage.setItem(INQUIRY_VITALS_AWAITING_KEY, data.session_id);
      window.setTimeout(() => onNavigate("vitals", { returnTo: "inquiry" }), 700);
    }
  }

  const handleTreatmentConfirm = useCallback(async (optionId) => {
    if (!sessionId || openingTreatmentRef.current) return;
    openingTreatmentRef.current = true;
    setOpeningTreatment(true);
    setTreatmentAction(null);
    try {
      const data = await confirmInquiryTreatment(sessionId, optionId);
      setTreatmentAction(data);
      setSession(data.session);
      notify(data.message || "方案对应药柜已处理");
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
  }, [notify, sessionId]);

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
    clearFaceIdentity();
    window.setTimeout(() => identifyFace({ force: true }).catch(() => null), 220);
  }

  const showResult = session?.stage === "result" || session?.stage === "escalated";

  return (
    <main className="inquiry-page conversation-layout" id="main-content">
      <aside className="inquiry-context-panel" aria-label="使用人信息">
        <section className="inquiry-user-card dynamic">
          <div className="context-heading user-context-heading">
            <UserRound size={26} aria-hidden="true" />
            <div className="user-context-copy"><span>使用人</span><h2>{displayedUser?.name || "等待确认"}</h2></div>
            <span className={`identity-confirmation-icon ${identityPresentation.tone}`} role="img" aria-label={identityPresentation.label} title={identityPresentation.label}>
              <IdentityIcon size={24} aria-hidden="true" />
            </span>
          </div>
          <div className="user-profile-grid">
            <article aria-label="年龄"><CakeSlice size={22} aria-hidden="true" /><strong>{displayedUser?.age ? `${displayedUser.age}岁` : "待补充"}</strong></article>
            <article aria-label="家庭身份"><House size={22} aria-hidden="true" /><strong>{displayedUser?.role || "待确认"}</strong></article>
          </div>
          <div className="user-health-facts">
            <article aria-label="基础病信息"><HeartPulse size={23} aria-hidden="true" /><strong>{displayedUser?.conditions || "基础病待补充"}</strong></article>
            <article aria-label="过敏和禁忌信息"><ShieldAlert size={23} aria-hidden="true" /><strong>{displayedUser?.allergies || "过敏禁忌待补充"}</strong></article>
            <article aria-label="病例备注"><NotebookText size={23} aria-hidden="true" /><strong>{displayedUser?.note || "通过语音继续补充"}</strong></article>
          </div>
        </section>
      </aside>

      <section className="inquiry-flow-card chat-only" aria-label="AI 应急问询流程">
        {!identityConfirmed ? (
          <InquiryIdentityGate candidate={candidateUser} status={faceIdentityStatus} onConfirm={confirmIdentity} onRetry={retryIdentity} onRequestGuest={confirmGuestInquiry} />
        ) : showResult ? (
          <InquiryResultStep
            result={session}
            opening={openingTreatment}
            actionResult={treatmentAction}
            onConfirmTreatment={handleTreatmentConfirm}
            onRestart={resetFlow}
            onHome={() => onNavigate("home")}
          />
        ) : session ? (
          <InquiryChatStep session={session} sending={sending} notify={notify} onSend={handleTurn} onReset={resetFlow} networkStatus={networkStatus} />
        ) : (
          <div className="inquiry-session-loading" role="status">正在建立本次问询...</div>
        )}
      </section>
    </main>
  );
}
