import React, { useEffect, useRef, useState } from "react";
import { CheckCircle2, Fingerprint, Minus, Plus, RotateCcw, ScanFace, ShieldCheck, UserRound, X } from "lucide-react";
import { identifyFingerprint } from "../api/fingerprint.js";
import { verifyDispenseIdentity } from "../api/identity.js";
import { activateIdentity } from "../hooks/useFaceIdentity.js";
import { StrokeDrawIcon } from "./StrokeDrawIcon.jsx";

const wait = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));
const nextPaint = () => new Promise((resolve) => {
  window.requestAnimationFrame(() => window.requestAnimationFrame(resolve));
});
const DISPENSE_FINGERPRINT_TIMEOUT_SECONDS = 15;
const FACE_PREVIEW_READY_TIMEOUT_MS = 4500;
const anonymousGuest = {
  id: "",
  name: "访客",
  status: "游客"
};

function isGuestIdentity(identity) {
  return !identity?.id || identity.id.startsWith("guest-") || ["访客", "游客"].includes(identity.status);
}

function faceFailureOutcome(verification = {}) {
  const status = String(verification.status || "unavailable");
  if (status === "no_face") {
    return {
      allowGuest: true,
      message: "未检测到可确认的人脸。可重新识别，或以访客身份继续。"
    };
  }
  if (["unknown", "unbound"].includes(status)) {
    return {
      allowGuest: true,
      message: "未匹配到已登记家庭成员。可重新识别，或以访客身份继续。"
    };
  }
  const originalMessage = String(verification.error_message || verification.message || "");
  return {
    allowGuest: false,
    message: originalMessage.includes("未返回有效结果")
      ? "人脸识别未返回有效结果。"
      : "人脸识别暂未完成，请重新识别。"
  };
}

export function DispenseConfirmModal({ medicine, plan = null, open, submitting, result, error, onCancel, onSubmit }) {
  const [quantity, setQuantity] = useState(1);
  const [method, setMethod] = useState(plan ? "fingerprint" : "face");
  const [phase, setPhase] = useState("idle");
  const [verificationError, setVerificationError] = useState("");
  const [verifiedIdentity, setVerifiedIdentity] = useState(null);
  const [guestTrigger, setGuestTrigger] = useState("");
  const [previewActive, setPreviewActive] = useState(false);
  const [previewRetry, setPreviewRetry] = useState(0);
  const [previewReady, setPreviewReady] = useState(false);
  const sessionRef = useRef(0);
  const verificationAttemptRef = useRef(0);
  const previewRetryTimerRef = useRef(null);
  const previewReadyTimerRef = useRef(null);
  const previewReadyWaiterRef = useRef(null);
  const busy = ["verifying", "recognized", "opening"].includes(phase) || submitting;

  useEffect(() => {
    if (open) {
      const initialMethod = plan ? "fingerprint" : "face";
      sessionRef.current += 1;
      verificationAttemptRef.current += 1;
      setQuantity(1);
      setMethod(initialMethod);
      setPhase("idle");
      setVerificationError("");
      setVerifiedIdentity(null);
      setGuestTrigger("");
      setPreviewActive(initialMethod === "face");
      setPreviewRetry(0);
      setPreviewReady(false);
    } else {
      sessionRef.current += 1;
      verificationAttemptRef.current += 1;
    }
    window.clearTimeout(previewRetryTimerRef.current);
    settlePreviewReadiness(false);
  }, [medicine?.id, open, plan?.id]);

  useEffect(() => {
    return () => {
      window.clearTimeout(previewRetryTimerRef.current);
      settlePreviewReadiness(false);
    };
  }, []);

  if (!open || !medicine) {
    return null;
  }

  function changeQuantity(nextQuantity) {
    setQuantity(Math.max(1, Math.min(30, nextQuantity)));
  }

  function selectMethod(nextMethod) {
    if (busy || phase === "guest_confirm" || nextMethod === method) {
      return;
    }
    verificationAttemptRef.current += 1;
    settlePreviewReadiness(false);
    setMethod(nextMethod);
    setPhase("idle");
    setVerificationError("");
    setVerifiedIdentity(null);
    setGuestTrigger("");
    setPreviewActive(nextMethod === "face");
    setPreviewReady(false);
    if (nextMethod === "face") {
      setPreviewRetry((current) => current + 1);
    }
    window.clearTimeout(previewRetryTimerRef.current);
  }

  function requestGuestConfirmation(
    identity = anonymousGuest,
    message = "",
    trigger = "manual"
  ) {
    verificationAttemptRef.current += 1;
    window.clearTimeout(previewRetryTimerRef.current);
    settlePreviewReadiness(false);
    setMethod("face");
    setPreviewActive(false);
    setPreviewReady(false);
    setVerifiedIdentity(identity);
    setVerificationError(message);
    setGuestTrigger(trigger);
    setPhase("guest_confirm");
  }

  function requestFaceRetryOnly(message = "人脸识别暂未完成，请重新识别。") {
    verificationAttemptRef.current += 1;
    const attempt = verificationAttemptRef.current;
    window.clearTimeout(previewRetryTimerRef.current);
    settlePreviewReadiness(false);
    setMethod("face");
    setPreviewActive(false);
    setPreviewReady(false);
    setPreviewRetry((current) => current + 1);
    setVerifiedIdentity(null);
    setVerificationError(message);
    setGuestTrigger("technical_failure");
    setPhase("face_retry");
    previewRetryTimerRef.current = window.setTimeout(() => {
      if (attempt === verificationAttemptRef.current) {
        setPreviewActive(true);
      }
    }, 180);
  }

  function resetFaceVerification() {
    setMethod("face");
    setPhase("idle");
    setVerifiedIdentity(null);
    setVerificationError("");
    setGuestTrigger("");
    void performVerification("face");
  }

  function retryPreview(attempt) {
    setPreviewReady(false);
    setPreviewActive(false);
    window.clearTimeout(previewRetryTimerRef.current);
    previewRetryTimerRef.current = window.setTimeout(() => {
      if (attempt !== verificationAttemptRef.current) return;
      setPreviewRetry((current) => current + 1);
      setPreviewActive(true);
    }, 360);
  }

  function waitForPreviewFrame(attempt) {
    settlePreviewReadiness(false);
    return new Promise((resolve) => {
      previewReadyWaiterRef.current = { attempt, resolve };
      previewReadyTimerRef.current = window.setTimeout(() => {
        settlePreviewReadiness(false, attempt);
      }, FACE_PREVIEW_READY_TIMEOUT_MS);
    });
  }

  function settlePreviewReadiness(ready, attempt = null) {
    const waiter = previewReadyWaiterRef.current;
    if (!waiter || (attempt !== null && waiter.attempt !== attempt)) {
      return;
    }
    window.clearTimeout(previewReadyTimerRef.current);
    previewReadyTimerRef.current = null;
    previewReadyWaiterRef.current = null;
    waiter.resolve(ready);
  }

  function handlePreviewReady(attempt) {
    if (attempt !== verificationAttemptRef.current) {
      return;
    }
    setPreviewReady(true);
    settlePreviewReadiness(true, attempt);
  }

  async function ensureFacePreviewReady(session, attempt) {
    if (previewActive && previewReady) {
      return true;
    }
    const previewFrame = waitForPreviewFrame(attempt);
    setPreviewActive(false);
    setPreviewReady(false);
    setPreviewRetry((current) => current + 1);
    await nextPaint();
    if (session !== sessionRef.current || attempt !== verificationAttemptRef.current) return false;
    setPreviewActive(true);
    await nextPaint();
    return previewFrame;
  }

  async function submitDispense(identity, verificationMethod, score, session) {
    setVerificationError("");
    setPhase("opening");
    const guest = isGuestIdentity(identity);
    if (guest) {
      activateIdentity(identity);
    }
    const dispense = await onSubmit({
      medicine_id: medicine.id,
      slot: medicine.slot,
      quantity,
      reason: guest ? "访客二次确认取药" : "家庭药柜取药确认",
      confirmed_safety_notice: true,
      confirm_real_dispense: true,
      target_user_id: identity?.id || "",
      target_user_name: identity?.name || anonymousGuest.name,
      verification_method: verificationMethod,
      verification_score: score ?? null,
      today_plan_id: guest ? "" : plan?.id || "",
      archive_identity_snapshot: guest && verificationMethod === "face_guest_confirmed"
    });
    if (dispense && dispense.ok === false) {
      throw new Error(dispense.message || "柜门未能打开");
    }
    if (session === sessionRef.current) {
      setGuestTrigger("");
      setPhase("complete");
    }
  }

  async function performVerification(selectedMethod) {
    const session = sessionRef.current;
    const attempt = verificationAttemptRef.current + 1;
    verificationAttemptRef.current = attempt;
    setVerificationError("");
    setGuestTrigger("");
    let verification;
    try {
      if (selectedMethod === "fingerprint") {
        setPhase("verifying");
        setPreviewActive(false);
        verification = await identifyFingerprint(DISPENSE_FINGERPRINT_TIMEOUT_SECONDS);
      } else {
        window.clearTimeout(previewRetryTimerRef.current);
        setPhase("idle");
        const previewIsReady = await ensureFacePreviewReady(session, attempt);
        if (session !== sessionRef.current || attempt !== verificationAttemptRef.current) return;
        if (!previewIsReady) {
          requestFaceRetryOnly("摄像头画面尚未就绪，请重新识别。");
          return;
        }
        setPhase("verifying");
        setPreviewActive(false);
        setPreviewReady(false);
        settlePreviewReadiness(false);
        await nextPaint();
        verification = await verifyDispenseIdentity(18);
      }
    } catch (requestError) {
      if (session !== sessionRef.current || attempt !== verificationAttemptRef.current) {
        return;
      }
      if (selectedMethod === "face") {
        requestFaceRetryOnly("人脸识别暂未完成，请重新识别。");
        return;
      }
      setPhase("idle");
      setVerificationError(requestError.message || "指纹确认未完成");
      return;
    }

    if (session !== sessionRef.current || attempt !== verificationAttemptRef.current) {
      return;
    }
    if (!verification?.ok || !verification?.user) {
      if (selectedMethod === "face") {
        const outcome = faceFailureOutcome(verification);
        if (outcome.allowGuest) {
          requestGuestConfirmation(anonymousGuest, outcome.message, "recognition_failed");
        } else {
          requestFaceRetryOnly(outcome.message);
        }
        return;
      }
      setPhase("idle");
      setVerificationError(verification?.error_message || verification?.message || "指纹确认未完成");
      return;
    }

    const guest = Boolean(verification.new_guest) || isGuestIdentity(verification.user);
    if (guest) {
      requestGuestConfirmation(
        verification.user,
        "未匹配到已登记家庭成员",
        "recognition_failed"
      );
      return;
    }
    if (plan?.service_user_id && verification.user.id !== plan.service_user_id) {
      setPhase("idle");
      setVerificationError(`该计划属于${plan.target_user}，请由本人完成身份确认`);
      setPreviewReady(false);
      setPreviewRetry((current) => current + 1);
      setPreviewActive(selectedMethod === "face");
      return;
    }

    setVerifiedIdentity(verification.user);
    activateIdentity(verification.user);
    setPhase("recognized");
    await wait(520);
    if (session !== sessionRef.current || attempt !== verificationAttemptRef.current) {
      return;
    }
    try {
      await submitDispense(verification.user, selectedMethod, verification.score, session);
    } catch (requestError) {
      if (session === sessionRef.current && attempt === verificationAttemptRef.current) {
        setPhase("idle");
        setVerificationError(requestError.message || "柜门未能打开");
        setPreviewActive(false);
      }
    }
  }

  async function verifyAndOpen() {
    if (busy || phase === "complete") {
      return;
    }
    const session = sessionRef.current;
    if (phase === "guest_confirm") {
      try {
        await submitDispense(verifiedIdentity || anonymousGuest, "face_guest_confirmed", null, session);
      } catch (requestError) {
        if (session === sessionRef.current) {
          setPhase("guest_confirm");
          setVerificationError(requestError.message || "游客取药确认未完成");
        }
      }
      return;
    }
    await performVerification(method);
  }

  function cancelSession() {
    sessionRef.current += 1;
    verificationAttemptRef.current += 1;
    window.clearTimeout(previewRetryTimerRef.current);
    settlePreviewReadiness(false);
    setPreviewActive(false);
    onCancel();
  }

  const stageTitle =
    phase === "verifying"
      ? method === "fingerprint" ? "正在读取指纹" : "正在确认面部"
      : phase === "face_retry"
        ? "面部识别未完成"
      : phase === "guest_confirm"
        ? "访客取药确认"
      : phase === "recognized"
        ? `${verifiedIdentity?.name || "使用人"}，身份已确认`
        : phase === "opening"
          ? "正在打开柜门"
          : phase === "complete"
            ? "柜门已打开"
            : method === "fingerprint" ? "指纹确认" : "面部确认";
  const stageDescription =
    phase === "recognized"
      ? `已确认${verifiedIdentity?.name || "使用人"}`
      : phase === "opening"
        ? `${medicine.hardware_slot || medicine.slot} 号柜即将开启`
      : phase === "complete"
          ? "请取出药品并关闭柜门"
          : "";
  const actionLabel =
    phase === "verifying"
      ? method === "fingerprint"
        ? "正在读取指纹"
        : "正在确认面部"
      : phase === "guest_confirm"
        ? "确认访客取药并开柜"
      : phase === "opening"
        ? "正在打开柜门"
        : phase === "recognized"
          ? "身份已确认"
        : phase === "complete"
          ? "柜门已打开"
          : method === "fingerprint"
            ? "确认身份并开柜"
            : "确认身份并开柜";
  const faceVerificationActive = method === "face" && phase === "verifying";
  const facePreviewVisible = method === "face" && ["idle", "face_retry"].includes(phase);
  const retryOnlyFaceFailure = method === "face" && phase === "face_retry";
  const failedGuestConfirmation = phase === "guest_confirm" && guestTrigger === "recognition_failed";
  const previewAttempt = verificationAttemptRef.current;

  return (
    <div className="modal-layer" role="presentation">
      <section className="dispense-modal biometric-dispense-modal" role="dialog" aria-modal="true" aria-labelledby="dispense-title">
        <button className="modal-close" type="button" onClick={cancelSession} aria-label="关闭取药确认" disabled={phase === "opening" || submitting}>
          <X size={24} aria-hidden="true" />
        </button>

        <div className="modal-heading">
          <span aria-hidden="true">
            <ShieldCheck size={34} strokeWidth={2.1} />
          </span>
          <div>
            <p>取药确认</p>
            <h2 id="dispense-title">{medicine.name}</h2>
          </div>
        </div>

        <div className="biometric-dispense-grid">
          <div className="dispense-summary-column">
            <div className="modal-medicine-meta compact-meta">
              <article>
                <span>当前使用人</span>
                <strong>{verifiedIdentity?.name || plan?.target_user || "等待确认"}</strong>
              </article>
              <article>
                <span>柜门</span>
                <strong>{medicine.hardware_slot || medicine.slot} 号</strong>
              </article>
              <article>
                <span>有效期</span>
                <strong>{medicine.expire_date}</strong>
              </article>
            </div>

            <div className="modal-usage-guidance">
              <strong>本次用法</strong>
              <span>{plan?.dose || medicine.safety_note || "请按药品说明使用"}</span>
              {plan?.frequency_label ? <small>{plan.frequency_label} · {plan.time}</small> : null}
            </div>

            <label className="quantity-control" htmlFor="dispense-quantity">
              <span>取药数量</span>
              <div>
                <button type="button" onClick={() => changeQuantity(quantity - 1)} aria-label="减少数量">
                  <Minus size={22} aria-hidden="true" />
                </button>
                <input
                  id="dispense-quantity"
                  type="number"
                  min="1"
                  max="30"
                  value={quantity}
                  onChange={(event) => changeQuantity(Number(event.target.value) || 1)}
                />
                <button type="button" onClick={() => changeQuantity(quantity + 1)} aria-label="增加数量">
                  <Plus size={22} aria-hidden="true" />
                </button>
              </div>
            </label>

            <div className="modal-warning compact-warning">
              <strong>用药提醒</strong>
              <span>{medicine.contraindications.slice(0, 2).join("；") || medicine.safety_note}</span>
            </div>

          </div>

          <div className="biometric-confirm-column">
            <div className="biometric-method-toggle" aria-label="身份确认方式">
              <button type="button" className={method === "fingerprint" ? "active" : ""} onClick={() => selectMethod("fingerprint")} disabled={busy || phase === "guest_confirm"}>
                <Fingerprint size={22} aria-hidden="true" />
                指纹
              </button>
              <button type="button" className={method === "face" ? "active" : ""} onClick={() => selectMethod("face")} disabled={busy || phase === "guest_confirm"}>
                <ScanFace size={22} aria-hidden="true" />
                面部
              </button>
            </div>

            <div className={`biometric-stage ${method} ${phase} ${phase !== "idle" ? "is-active" : ""}`}>
              {facePreviewVisible && previewActive ? (
                <>
                  <img
                    key={`${previewAttempt}-${previewRetry}`}
                    className={previewReady ? "ready" : "loading"}
                    src={`/api/camera/stream?identity=${previewRetry}`}
                    alt=""
                    onLoad={() => handlePreviewReady(previewAttempt)}
                    onError={() => retryPreview(previewAttempt)}
                  />
                  {!previewReady && <StrokeDrawIcon icon={ScanFace} size={82} strokeWidth={1.8} mode="yoyo" active />}
                </>
              ) : phase === "guest_confirm" ? (
                <span className="biometric-confirmed-glyph guest" aria-hidden="true">
                  <UserRound size={88} strokeWidth={1.8} />
                </span>
              ) : ["recognized", "complete"].includes(phase) ? (
                <span className="biometric-confirmed-glyph" aria-hidden="true">
                  <CheckCircle2 size={88} strokeWidth={1.8} />
                </span>
              ) : (
                <StrokeDrawIcon
                  icon={method === "fingerprint" ? Fingerprint : ScanFace}
                  size={92}
                  strokeWidth={1.8}
                  mode="yoyo"
                  active={phase !== "idle"}
                />
              )}
              {!faceVerificationActive ? (
                <>
                  <div className="biometric-stage-title-row">
                    <strong>{stageTitle}</strong>
                  </div>
                  {stageDescription ? <span className="biometric-stage-description">{stageDescription}</span> : null}
                </>
              ) : null}
            </div>

            {!result && (verificationError || error) && (
              <p className={`modal-message ${phase === "guest_confirm" ? "guest" : "error"}`}>
                {verificationError || error}
              </p>
            )}
            {result && <p className="modal-message success">{result}</p>}

            <div className={`biometric-action-row ${faceVerificationActive || failedGuestConfirmation ? "split" : ""}`}>
              {faceVerificationActive ? (
                <>
                  <button className="primary-action biometric-confirm-action" type="button" disabled>
                    <ScanFace size={24} aria-hidden="true" />
                    <span>正在确认面部</span>
                  </button>
                  <button
                    className="secondary-action biometric-guest-action"
                    type="button"
                    onClick={() => requestGuestConfirmation(anonymousGuest, "", "manual")}
                  >
                    <UserRound size={22} aria-hidden="true" />
                    <span>访客取药</span>
                  </button>
                </>
              ) : retryOnlyFaceFailure ? (
                <button type="button" className="primary-action biometric-confirm-action" onClick={resetFaceVerification}>
                  <RotateCcw size={21} aria-hidden="true" />
                  <span>重新识别</span>
                </button>
              ) : failedGuestConfirmation ? (
                <>
                  <button type="button" className="secondary-action guest-confirm-retry" onClick={resetFaceVerification}>
                    <RotateCcw size={21} aria-hidden="true" />
                    <span>重新识别</span>
                  </button>
                  <button className="primary-action biometric-confirm-action" type="button" onClick={verifyAndOpen}>
                    <UserRound size={22} aria-hidden="true" />
                    <span>确认访客取药</span>
                  </button>
                </>
              ) : (
                <button
                  className="primary-action biometric-confirm-action"
                  type="button"
                  disabled={busy || phase === "complete"}
                  onClick={verifyAndOpen}
                >
                  {phase === "complete" ? <CheckCircle2 size={24} aria-hidden="true" /> : method === "fingerprint" ? <Fingerprint size={24} aria-hidden="true" /> : <ScanFace size={24} aria-hidden="true" />}
                  <span>{actionLabel}</span>
                </button>
              )}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
