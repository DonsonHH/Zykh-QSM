import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, CheckCircle2, Fingerprint, History, LoaderCircle, RotateCcw, ScanFace, ShieldCheck, UserRound, X, XCircle } from "lucide-react";
import { identifyFingerprint } from "../api/fingerprint.js";
import { verifyDispenseIdentity } from "../api/identity.js";
import { confirmMedicineInventory } from "../api/medicines.js";
import { activateIdentity } from "../hooks/useFaceIdentity.js";
import { useExitPresence } from "../hooks/useExitPresence.js";
import { speakText, stopAudioPlayback } from "../api/audio.js";
import { turnOffCabinetLight } from "../api/qsm.js";
import {
  buildDispenseFailureSpeech,
  buildDispenseGuidanceSpeech,
  buildDispenseSuccessSpeech,
  resolveDispenseUsage
} from "../utils/dispenseSpeech.js";
import {
  describeMedicineCabinet,
  normalizeCabinetLightMessage
} from "../utils/cabinetLightPresentation.js";
import { MedicineRemainingPrompt } from "./MedicineRemainingPrompt.jsx";
import { StrokeDrawIcon } from "./StrokeDrawIcon.jsx";

const wait = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));
const nextPaint = () => new Promise((resolve) => {
  window.requestAnimationFrame(() => window.requestAnimationFrame(resolve));
});
const DISPENSE_FINGERPRINT_TIMEOUT_SECONDS = 15;
const FACE_PREVIEW_READY_TIMEOUT_MS = 4500;
const FACE_VERIFICATION_FRAME_INTERVAL_MS = 250;
const anonymousGuest = {
  id: "",
  name: "访客",
  status: "游客"
};

function createManualRequestId(kind) {
  const suffix = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `manual-${kind}-${suffix}`;
}

function isGuestIdentity(identity) {
  return !identity?.id || identity.id.startsWith("guest-") || ["访客", "游客"].includes(identity.status);
}

function dispenseRequestMayHaveReachedHardware(error) {
  const responseStatus = Number(error?.status);
  return !Number.isInteger(responseStatus) || responseStatus >= 500;
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

export function DispenseConfirmModal({ medicine: currentMedicine, plan = null, manualAccess = false, open, submitting, result, error, onCancel, onSubmit, onAssessManual, onConfirmManual }) {
  const medicineRef = useRef(currentMedicine);
  if (currentMedicine) medicineRef.current = currentMedicine;
  const medicine = currentMedicine || medicineRef.current;
  const { present, exiting } = useExitPresence(Boolean(open && currentMedicine));
  const [method, setMethod] = useState(plan ? "fingerprint" : "face");
  const [phase, setPhase] = useState("idle");
  const [verificationError, setVerificationError] = useState("");
  const [verifiedIdentity, setVerifiedIdentity] = useState(null);
  const [guestTrigger, setGuestTrigger] = useState("");
  const [previewActive, setPreviewActive] = useState(false);
  const [previewRetry, setPreviewRetry] = useState(0);
  const [previewReady, setPreviewReady] = useState(false);
  const [verificationFrameVersion, setVerificationFrameVersion] = useState(0);
  const [verificationFrameReady, setVerificationFrameReady] = useState(false);
  const [inventoryUpdating, setInventoryUpdating] = useState(false);
  const [inventoryMessage, setInventoryMessage] = useState("");
  const [inventoryError, setInventoryError] = useState("");
  const [inventoryConfirmedState, setInventoryConfirmedState] = useState("");
  const [dispenseRecordId, setDispenseRecordId] = useState("");
  const [inventoryEligible, setInventoryEligible] = useState(false);
  const [lightOffBusy, setLightOffBusy] = useState(false);
  const [lightOffError, setLightOffError] = useState("");
  const [manualAssessment, setManualAssessment] = useState(null);
  const sessionRef = useRef(0);
  const verificationAttemptRef = useRef(0);
  const previewRetryTimerRef = useRef(null);
  const previewReadyTimerRef = useRef(null);
  const previewReadyWaiterRef = useRef(null);
  const autoCloseTimerRef = useRef(null);
  const inventoryRequestIdRef = useRef("");
  const cabinetLightMayBeOnRef = useRef(false);
  const spokenAnnouncementsRef = useRef(new Set());
  const onCancelRef = useRef(onCancel);
  const manualInventory = Boolean(manualAccess);
  const busy = ["verifying", "recognized", "checking", "opening"].includes(phase) || submitting || lightOffBusy;
  const manualIdentityLocked = manualInventory && [
    "recognized",
    "checking",
    "passed",
    "blocked",
    "check_failed",
    "opening",
    "complete",
    "dispense_failed",
    "result_unknown"
  ].includes(phase);
  const manualTerminalFailure = manualInventory && [
    "blocked",
    "check_failed",
    "dispense_failed"
  ].includes(phase);

  useEffect(() => {
    onCancelRef.current = onCancel;
  }, [onCancel]);

  useEffect(() => {
    if (open) {
      if (cabinetLightMayBeOnRef.current) {
        cabinetLightMayBeOnRef.current = false;
        void turnOffCabinetLight().catch(() => undefined);
      }
      const initialMethod = plan ? "fingerprint" : "face";
      sessionRef.current += 1;
      verificationAttemptRef.current += 1;
      setMethod(initialMethod);
      setPhase("idle");
      setVerificationError("");
      setVerifiedIdentity(null);
      setGuestTrigger("");
      setPreviewActive(initialMethod === "face");
      setPreviewRetry(0);
      setPreviewReady(false);
      setVerificationFrameVersion(0);
      setVerificationFrameReady(false);
      setInventoryUpdating(false);
      setInventoryMessage("");
      setInventoryError("");
      setInventoryConfirmedState("");
      setDispenseRecordId("");
      setInventoryEligible(false);
      setLightOffBusy(false);
      setLightOffError("");
      cabinetLightMayBeOnRef.current = false;
      inventoryRequestIdRef.current = "";
      setManualAssessment(null);
      spokenAnnouncementsRef.current.clear();
    } else {
      sessionRef.current += 1;
      verificationAttemptRef.current += 1;
      if (cabinetLightMayBeOnRef.current) {
        cabinetLightMayBeOnRef.current = false;
        void turnOffCabinetLight().catch(() => undefined);
      }
    }
    window.clearTimeout(previewRetryTimerRef.current);
    window.clearTimeout(autoCloseTimerRef.current);
    settlePreviewReadiness(false);
  }, [medicine?.id, open, plan?.id]);

  useEffect(() => {
    return () => {
      window.clearTimeout(previewRetryTimerRef.current);
      window.clearTimeout(autoCloseTimerRef.current);
      settlePreviewReadiness(false);
      if (cabinetLightMayBeOnRef.current) {
        cabinetLightMayBeOnRef.current = false;
        void turnOffCabinetLight().catch(() => undefined);
      }
    };
  }, []);

  useEffect(() => {
    if (!open || method !== "face" || phase !== "verifying") {
      setVerificationFrameReady(false);
      return undefined;
    }
    setVerificationFrameVersion(Date.now());
    const interval = window.setInterval(() => {
      setVerificationFrameVersion(Date.now());
    }, FACE_VERIFICATION_FRAME_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [method, open, phase]);

  useEffect(() => {
    if (!open || !medicine) return undefined;
    const timer = window.setTimeout(() => {
      playSpeech(
        `guidance:${medicine.id}:${plan?.id || "manual"}:${method}`,
        buildDispenseGuidanceSpeech(medicine, plan, method)
      );
    }, 180);
    return () => window.clearTimeout(timer);
  }, [medicine?.id, method, open, plan?.id]);

  useEffect(() => {
    if (!open || !medicine) return;
    if (phase === "complete") {
      playSpeech(`complete:${medicine.id}`, buildDispenseSuccessSpeech(medicine));
      return;
    }
    const failure = normalizeCabinetLightMessage(verificationError || error);
    if (failure && !["verifying", "recognized", "opening"].includes(phase)) {
      playSpeech(`failure:${phase}:${failure}`, buildDispenseFailureSpeech(failure));
    }
  }, [error, medicine?.id, open, phase, verificationError]);

  if (!present || !medicine) {
    return null;
  }

  function playSpeech(key, text) {
    if (!text || spokenAnnouncementsRef.current.has(key)) return;
    spokenAnnouncementsRef.current.add(key);
    const session = sessionRef.current;
    void stopAudioPlayback()
      .catch(() => undefined)
      .then(() => {
        if (session === sessionRef.current) {
          return speakText(text, undefined, 1.12);
        }
        return undefined;
      })
      .catch(() => undefined);
  }

  function selectMethod(nextMethod) {
    if (busy || manualIdentityLocked || phase === "guest_confirm" || nextMethod === method) {
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
    const attempt = verificationAttemptRef.current + 1;
    verificationAttemptRef.current = attempt;
    window.clearTimeout(previewRetryTimerRef.current);
    settlePreviewReadiness(false);
    setMethod("face");
    setVerifiedIdentity(identity);
    setVerificationError(message);
    setGuestTrigger(trigger);
    setPhase("guest_confirm");
    resumeFacePreview(attempt);
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
    resumeFacePreview(attempt);
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
    resumeFacePreview(attempt, 360);
  }

  function resumeFacePreview(attempt, delay = 220) {
    setPreviewReady(false);
    setPreviewActive(false);
    setPreviewRetry((current) => current + 1);
    window.clearTimeout(previewRetryTimerRef.current);
    previewRetryTimerRef.current = window.setTimeout(() => {
      if (attempt === verificationAttemptRef.current) {
        setPreviewActive(true);
      }
    }, delay);
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

  function handlePreviewError(attempt) {
    if (phase === "verifying") {
      return;
    }
    retryPreview(attempt);
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
    let dispense;
    try {
      dispense = await onSubmit({
        medicine_id: medicine.id,
        slot: medicine.slot,
        quantity: 1,
        reason: guest ? "访客二次确认取药" : "家庭分类柜取药确认",
        confirmed_safety_notice: true,
        confirm_real_dispense: true,
        target_user_id: identity?.id || "",
        target_user_name: identity?.name || anonymousGuest.name,
        verification_method: verificationMethod,
        verification_score: score ?? null,
        today_plan_id: guest ? "" : plan?.id || "",
        archive_identity_snapshot: guest && verificationMethod === "face_guest_confirmed"
      });
    } catch (requestError) {
      if (session === sessionRef.current && dispenseRequestMayHaveReachedHardware(requestError)) {
        cabinetLightMayBeOnRef.current = true;
        setVerificationError(normalizeCabinetLightMessage(
          `${requestError.message || "分类柜亮灯服务未返回可确认结果"}。亮灯结果待现场确认，请勿重复操作。`
        ));
        setPhase("result_unknown");
        return;
      }
      throw requestError;
    }
    if (dispense?.result_unknown || (dispense?.ok === false && dispense?.retry_safe === false)) {
      if (session === sessionRef.current) {
        setGuestTrigger("");
        setDispenseRecordId(String(dispense?.record_id || ""));
        setInventoryEligible(false);
        cabinetLightMayBeOnRef.current = true;
        setVerificationError(normalizeCabinetLightMessage(
          dispense?.message || "分类柜亮灯结果待现场确认，请勿重复操作。"
        ));
        setPhase("result_unknown");
      }
      return;
    }
    if (dispense && dispense.ok === false) {
      throw new Error(normalizeCabinetLightMessage(dispense.message || "分类柜指示灯未能点亮"));
    }
    if (session === sessionRef.current) {
      setGuestTrigger("");
      setDispenseRecordId(String(dispense?.record_id || ""));
      setInventoryEligible(Boolean(dispense?.inventory_confirmation_required));
      inventoryRequestIdRef.current = createManualRequestId("inventory");
      cabinetLightMayBeOnRef.current = true;
      setPhase("complete");
    }
  }

  async function assessManualAccess(identity, verification, verificationMethod, session, attempt) {
    setPreviewActive(false);
    setVerificationError("");
    setPhase("checking");
    const assertionId = String(verification?.verification_assertion_id || "").trim();
    const reviewFingerprint = String(medicine.review_fingerprint || "").trim();
    if (!identity?.id || !assertionId || !reviewFingerprint || !onAssessManual) {
      if (session !== sessionRef.current || attempt !== verificationAttemptRef.current) return;
      setManualAssessment({
        check_status: "CHECK_FAILED",
        reason_codes: ["PROFILE_UNAVAILABLE"],
        message: "身份凭据或药品核验资料不完整，本次分类柜指示灯未亮。",
        persisted: false
      });
      setPhase("check_failed");
      return;
    }
    try {
      const assessment = await onAssessManual({
        request_id: createManualRequestId("assess"),
        medicine_id: medicine.id,
        slot: String(medicine.slot),
        service_user_id: identity.id,
        verification_method: verificationMethod,
        verification_assertion_id: assertionId,
        expected_review_fingerprint: reviewFingerprint
      });
      if (session !== sessionRef.current || attempt !== verificationAttemptRef.current) return;
      const status = String(assessment?.check_status || "CHECK_FAILED").toUpperCase();
      setManualAssessment(assessment
        ? { ...assessment, persisted: true }
        : {
          check_status: "CHECK_FAILED",
          reason_codes: ["MEDICINE_DATA_UNREVIEWED"],
          message: "未能完成可靠核查，本次分类柜指示灯未亮。",
          persisted: false
        });
      setPhase(status === "PASSED" ? "passed" : status === "BLOCKED" ? "blocked" : "check_failed");
    } catch (requestError) {
      if (session !== sessionRef.current || attempt !== verificationAttemptRef.current) return;
      const message = requestError.message || "个人用药安全核查失败";
      setManualAssessment({
        check_status: "CHECK_FAILED",
        reason_codes: ["PROFILE_UNAVAILABLE"],
        message: `${message}，本次分类柜指示灯未亮。`,
        persisted: false
      });
      setPhase("check_failed");
    }
  }

  async function confirmManualAccess() {
    if (phase !== "passed" || !manualAssessment?.check_id || !onConfirmManual) return;
    const session = sessionRef.current;
    setVerificationError("");
    setPhase("opening");
    try {
      const outcome = await onConfirmManual({
        request_id: createManualRequestId("confirm"),
        safety_check_id: manualAssessment.check_id,
        confirmed_safety_notice: true
      });
      if (session !== sessionRef.current) return;
      if (outcome?.ok && outcome.dispense_status === "DISPENSED") {
        setDispenseRecordId(String(outcome.dispense_record_id || ""));
        setInventoryEligible(Boolean(outcome.inventory_confirmation_required));
        inventoryRequestIdRef.current = createManualRequestId("inventory");
        cabinetLightMayBeOnRef.current = true;
        setPhase("complete");
        return;
      }
      setManualAssessment((current) => ({
        ...current,
        dispense_status: outcome?.dispense_status || "HARDWARE_FAILED",
        message: normalizeCabinetLightMessage(outcome?.message || "分类柜指示灯未能点亮，请联系值守员。")
      }));
      if (outcome?.dispense_status === "RESULT_UNKNOWN") {
        cabinetLightMayBeOnRef.current = true;
        setPhase("result_unknown");
      } else {
        setPhase("dispense_failed");
      }
    } catch (requestError) {
      if (session !== sessionRef.current) return;
      const responseStatus = Number(requestError.status);
      if (!Number.isInteger(responseStatus) || responseStatus >= 500) {
        const detail = normalizeCabinetLightMessage(requestError.message || "分类柜亮灯服务未返回可确认结果");
        cabinetLightMayBeOnRef.current = true;
        setManualAssessment((current) => ({
          ...current,
          dispense_status: "RESULT_UNKNOWN",
          message: `${detail}。分类柜亮灯结果暂无法确认，请勿重复操作。`
        }));
        setPhase("result_unknown");
        return;
      }
      if (responseStatus >= 400 && responseStatus < 500) {
        const detail = requestError.message || "本次安全核查确认未通过";
        setManualAssessment((current) => ({
          ...current,
          check_status: "CHECK_FAILED",
          dispense_status: "NOT_STARTED",
          message: `${detail}，本次分类柜指示灯未亮。`,
          persisted: false
        }));
        setPhase("check_failed");
        return;
      }
      setManualAssessment((current) => ({
        ...current,
        dispense_status: "HARDWARE_FAILED",
        message: normalizeCabinetLightMessage(requestError.message || "分类柜指示灯未能点亮，请联系值守员。")
      }));
      setPhase("dispense_failed");
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
        if (outcome.allowGuest && manualInventory) {
          setPreviewActive(false);
          setVerifiedIdentity(anonymousGuest);
          setManualAssessment({
            check_status: "CHECK_FAILED",
            reason_codes: ["PROFILE_UNAVAILABLE"],
            message: "未确认到可用于个人用药核查的已登记身份，本次分类柜指示灯未亮。",
            persisted: false
          });
          setPhase("check_failed");
        } else if (outcome.allowGuest) {
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
      if (manualInventory) {
        setVerifiedIdentity(verification.user);
        setPhase("recognized");
        setPreviewActive(false);
        await assessManualAccess(verification.user, verification, selectedMethod, session, attempt);
        return;
      }
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
      if (selectedMethod === "face") {
        resumeFacePreview(attempt);
      }
      return;
    }

    setVerifiedIdentity(verification.user);
    activateIdentity(verification.user);
    setPhase("recognized");
    if (selectedMethod === "face") {
      resumeFacePreview(attempt);
    }
    await wait(520);
    if (session !== sessionRef.current || attempt !== verificationAttemptRef.current) {
      return;
    }
    if (manualInventory) {
      await assessManualAccess(verification.user, verification, selectedMethod, session, attempt);
      return;
    }
    try {
      await submitDispense(verification.user, selectedMethod, verification.score, session);
    } catch (requestError) {
      if (session === sessionRef.current && attempt === verificationAttemptRef.current) {
        setPhase("idle");
        setVerificationError(normalizeCabinetLightMessage(requestError.message || "分类柜指示灯未能点亮"));
        if (selectedMethod === "face") {
          resumeFacePreview(attempt);
        }
      }
    }
  }

  async function verifyAndOpen() {
    if (busy || phase === "complete") {
      return;
    }
    if (phase === "passed") {
      await confirmManualAccess();
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
    window.clearTimeout(autoCloseTimerRef.current);
    settlePreviewReadiness(false);
    setPreviewActive(false);
    if (cabinetLightMayBeOnRef.current) {
      cabinetLightMayBeOnRef.current = false;
      void turnOffCabinetLight().catch(() => undefined);
    }
    void stopAudioPlayback().catch(() => undefined);
    onCancelRef.current();
  }

  async function acknowledgeMedicineTaken() {
    if (phase !== "complete" || lightOffBusy) return;
    const session = sessionRef.current;
    setLightOffBusy(true);
    setLightOffError("");
    try {
      await turnOffCabinetLight();
      if (session !== sessionRef.current) return;
      cabinetLightMayBeOnRef.current = false;
      if (inventoryEligible && dispenseRecordId) {
        setPhase("inventory_check");
      } else {
        cancelSession();
      }
    } catch (requestError) {
      if (session === sessionRef.current) {
        setLightOffError(normalizeCabinetLightMessage(
          requestError.message || "指示灯关闭失败，请重试或联系值守员。"
        ));
      }
    } finally {
      if (session === sessionRef.current) setLightOffBusy(false);
    }
  }

  async function closeUncertainCabinetLight() {
    if (phase !== "result_unknown" || lightOffBusy) return;
    const session = sessionRef.current;
    setLightOffBusy(true);
    setLightOffError("");
    try {
      await turnOffCabinetLight();
      if (session !== sessionRef.current) return;
      cabinetLightMayBeOnRef.current = false;
      cancelSession();
    } catch (requestError) {
      if (session === sessionRef.current) {
        setLightOffError(normalizeCabinetLightMessage(
          requestError.message || "指示灯关闭失败，请重试或联系值守员。"
        ));
      }
    } finally {
      if (session === sessionRef.current) setLightOffBusy(false);
    }
  }

  async function confirmInventory(observation) {
    if (inventoryUpdating) return;
    if (!dispenseRecordId) {
      setInventoryError("缺少本次取药记录，无法更新库存；请联系值守员核对。");
      return;
    }
    setInventoryUpdating(true);
    setInventoryError("");
    try {
      if (!inventoryRequestIdRef.current) {
        inventoryRequestIdRef.current = createManualRequestId("inventory");
      }
      const response = await confirmMedicineInventory(medicine.id, {
        request_id: inventoryRequestIdRef.current,
        dispense_record_id: dispenseRecordId,
        observation
      });
      const updatedMedicine = {
        ...medicine,
        stock: response.stock,
        inventory_state: response.inventory_state,
        inventory_confirmed_at: response.inventory_confirmed_at,
        last_inventory_request_id: inventoryRequestIdRef.current,
        last_inventory_dispense_record_id: dispenseRecordId
      };
      window.dispatchEvent(new CustomEvent("zykh:medicine-updated", { detail: updatedMedicine }));
      setInventoryConfirmedState(response.inventory_state);
      setInventoryMessage(observation === "DEPLETED" ? "已触发库存警告" : "已确认分类柜内还有药");
      autoCloseTimerRef.current = window.setTimeout(cancelSession, 900);
    } catch (requestError) {
      setInventoryError(requestError.message || "库存确认未保存，请重新选择或联系值守员核对");
    } finally {
      setInventoryUpdating(false);
    }
  }

  const stageTitle =
    phase === "inventory_check"
      ? "库存确认"
      : phase === "verifying"
      ? method === "fingerprint" ? "正在读取指纹" : "正在确认面部"
      : phase === "face_retry"
        ? "面部识别未完成"
      : phase === "guest_confirm"
        ? "访客取药确认"
      : phase === "checking"
        ? "正在核查个人用药安全"
      : phase === "passed"
        ? "个人用药安全核查通过"
      : phase === "blocked"
        ? "已阻止本次取药"
      : phase === "check_failed"
        ? "本次核查未完成"
      : phase === "dispense_failed"
        ? "分类柜指示灯未能点亮"
      : phase === "result_unknown"
        ? "亮灯结果待现场确认"
      : phase === "recognized"
        ? `${verifiedIdentity?.name || "使用人"}，身份已确认`
        : phase === "opening"
          ? "正在点亮分类柜指示灯"
          : phase === "complete"
            ? "分类柜指示灯已亮"
            : method === "fingerprint" ? "指纹确认" : "面部确认";
  const stageDescription =
    phase === "recognized"
      ? `已确认${verifiedIdentity?.name || "使用人"}`
      : phase === "opening"
        ? `${describeMedicineCabinet(medicine)}即将亮灯`
      : phase === "complete"
          ? "请自行打开亮灯的分类柜取药，取好后点击下方按钮"
      : phase === "result_unknown"
        ? "请勿再次点亮；现场确认后关闭分类柜指示灯"
          : "";
  const actionLabel =
    phase === "verifying"
      ? method === "fingerprint"
        ? "正在读取指纹"
        : "正在确认面部"
      : phase === "guest_confirm"
        ? "确认访客取药并亮灯"
      : phase === "checking"
        ? "正在核查"
      : phase === "passed"
        ? "确认取药并亮灯"
      : phase === "opening"
        ? "正在点亮指示灯"
        : phase === "recognized"
          ? "身份已确认"
        : phase === "complete"
          ? "我已取药，关闭指示灯"
          : method === "fingerprint"
            ? "确认身份并点亮分类柜"
            : "确认身份并点亮分类柜";
  const faceVerificationActive = method === "face" && phase === "verifying";
  const facePreviewVisible = method === "face" && previewActive;
  const retryOnlyFaceFailure = method === "face" && phase === "face_retry";
  const failedGuestConfirmation = phase === "guest_confirm" && guestTrigger === "recognition_failed";
  const previewAttempt = verificationAttemptRef.current;
  const planScheduleNote = plan
    ? [...new Set([plan.time, plan.timing_label, plan.frequency_label].filter(Boolean))].join(" · ")
    : "";
  const dispenseUsage = resolveDispenseUsage(medicine, plan);

  return createPortal(
    <div className={`modal-layer${exiting ? " is-exiting" : ""}`} role="presentation">
      <section className="dispense-modal biometric-dispense-modal" role="dialog" aria-modal="true" aria-labelledby="dispense-title">
        <button className="modal-close" type="button" onClick={cancelSession} aria-label="关闭取药确认" disabled={phase === "opening" || phase === "complete" || phase === "result_unknown" || submitting || lightOffBusy}>
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

        {phase === "inventory_check" ? (
          <MedicineRemainingPrompt
            medicine={medicine}
            busy={inventoryUpdating}
            message={inventoryMessage}
            error={inventoryError}
            confirmedState={inventoryConfirmedState}
            cabinetLightOff
            onHasStock={() => confirmInventory("HAS_REMAINING")}
            onDepleted={() => confirmInventory("DEPLETED")}
          />
        ) : <div className="biometric-dispense-grid">
          <div className="dispense-summary-column">
            <div className="modal-medicine-meta compact-meta">
              <article>
                <span>当前使用人</span>
                <strong>{verifiedIdentity?.name || plan?.target_user || "等待确认"}</strong>
              </article>
              <article>
                <span>分类柜</span>
                <strong>{describeMedicineCabinet(medicine)}</strong>
              </article>
              <article>
                <span>有效期</span>
                <strong>{medicine.expire_date}</strong>
              </article>
            </div>

            <div className="modal-usage-guidance">
              <strong>本次用法</strong>
              <span>{dispenseUsage}</span>
              {planScheduleNote ? <small>{planScheduleNote}</small> : null}
            </div>

            <div className="dispense-history-summary" aria-label={`该药历史成功取药 ${medicine.dispense_count || 0} 次`}>
              <span className="dispense-history-icon" aria-hidden="true">
                <History size={25} />
              </span>
              <div>
                <span>历史取药次数</span>
                <strong>{medicine.dispense_count || 0}<small>次</small></strong>
              </div>
              <p>仅统计已成功点亮分类柜指示灯的取药记录</p>
            </div>

            <div className="modal-warning compact-warning">
              <strong>用药提醒</strong>
              <div className="compact-warning-list">
                {medicine.contraindications?.length ? (
                  <span><b>禁忌提醒：</b>{medicine.contraindications.slice(0, 2).join("；")}</span>
                ) : null}
                {medicine.safety_note ? (
                  <span><b>慎用与指导提醒：</b>{medicine.safety_note}</span>
                ) : null}
              </div>
            </div>

          </div>

          <div className="biometric-confirm-column">
            <div className="biometric-method-toggle" aria-label="身份确认方式">
              <button type="button" className={method === "fingerprint" ? "active" : ""} onClick={() => selectMethod("fingerprint")} disabled={busy || manualIdentityLocked || phase === "guest_confirm"}>
                <Fingerprint size={22} aria-hidden="true" />
                指纹
              </button>
              <button type="button" className={method === "face" ? "active" : ""} onClick={() => selectMethod("face")} disabled={busy || manualIdentityLocked || phase === "guest_confirm"}>
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
                    onError={() => handlePreviewError(previewAttempt)}
                  />
                  {faceVerificationActive ? (
                    <img
                      className={`face-verification-preview ${verificationFrameReady ? "ready" : "loading"}`}
                      src={`/api/identity/frame?t=${verificationFrameVersion}`}
                      alt=""
                      onLoad={() => setVerificationFrameReady(true)}
                    />
                  ) : null}
                  {!previewReady && <StrokeDrawIcon icon={ScanFace} size={82} strokeWidth={1.8} mode="yoyo" active />}
                </>
              ) : phase === "guest_confirm" ? (
                <span className="biometric-confirmed-glyph guest" aria-hidden="true">
                  <UserRound size={88} strokeWidth={1.8} />
                </span>
              ) : ["recognized", "passed", "complete"].includes(phase) ? (
                <span className="biometric-confirmed-glyph" aria-hidden="true">
                  <CheckCircle2 size={88} strokeWidth={1.8} />
                </span>
              ) : phase === "checking" ? (
                <span className="manual-access-state-glyph checking" aria-hidden="true">
                  <LoaderCircle className="manual-access-stage-spinner" size={76} strokeWidth={1.8} />
                </span>
              ) : phase === "blocked" ? (
                <span className="manual-access-state-glyph blocked" aria-hidden="true">
                  <AlertTriangle size={76} strokeWidth={1.8} />
                </span>
              ) : ["check_failed", "dispense_failed", "result_unknown"].includes(phase) ? (
                <span className="manual-access-state-glyph failed" aria-hidden="true">
                  <XCircle size={76} strokeWidth={1.8} />
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
              {facePreviewVisible ? null : !faceVerificationActive ? (
                <>
                  <div className="biometric-stage-title-row" role="status" aria-live="polite">
                    <strong>{stageTitle}</strong>
                  </div>
                  {stageDescription ? <span className="biometric-stage-description">{stageDescription}</span> : null}
                </>
              ) : null}
            </div>

            {phase === "checking" ? (
              <p className="manual-access-progress" role="status" aria-live="polite">
                正在核查已登记档案与药品安全信息…
              </p>
            ) : null}
            {!result && (verificationError || error) && (
              <p className={`modal-message ${phase === "guest_confirm" ? "guest" : "error"}`}>
                {normalizeCabinetLightMessage(verificationError || error)}
              </p>
            )}
            {result && <p className="modal-message success">{normalizeCabinetLightMessage(result)}</p>}
            {lightOffError ? <p className="modal-message error" role="alert">{lightOffError}</p> : null}
            {phase === "result_unknown" && !manualAssessment ? (
              <div className="manual-access-result" data-status="result_unknown" role="alert">
                <strong>请勿重复操作</strong>
                <p>{normalizeCabinetLightMessage(verificationError || error || "分类柜亮灯结果待现场确认。")}</p>
                <small>请现场确认指示灯状态，并使用下方按钮安全关灯</small>
              </div>
            ) : null}
            {manualAssessment && ["passed", "blocked", "check_failed", "dispense_failed", "result_unknown"].includes(phase) ? (
              <div
                className="manual-access-result"
                data-status={phase}
                role={phase === "passed" ? "status" : "alert"}
              >
                <strong>{phase === "passed"
                  ? "核查通过"
                  : phase === "blocked"
                    ? "已阻止取药"
                    : phase === "check_failed"
                      ? "未能完成核查"
                      : phase === "result_unknown"
                        ? "请勿重复操作"
                        : "分类柜亮灯未完成"}</strong>
                <p>{normalizeCabinetLightMessage(manualAssessment.message)}</p>
                {(phase === "blocked" || phase === "check_failed") && manualAssessment.persisted
                  ? <small>已记录并将同步家属</small>
                  : null}
                {phase === "result_unknown" ? <small>请现场确认指示灯状态，并使用下方按钮安全关灯</small> : null}
              </div>
            ) : null}

            <div className={`biometric-action-row ${(!manualInventory && faceVerificationActive) || failedGuestConfirmation ? "split" : ""}`}>
              {phase === "result_unknown" ? (
                <button
                  className="primary-action biometric-confirm-action"
                  type="button"
                  disabled={lightOffBusy}
                  onClick={closeUncertainCabinetLight}
                >
                  {lightOffBusy ? <LoaderCircle className="spin" size={24} aria-hidden="true" /> : <CheckCircle2 size={24} aria-hidden="true" />}
                  <span>{lightOffBusy ? "正在关闭指示灯" : "关闭分类柜指示灯"}</span>
                </button>
              ) : manualTerminalFailure ? (
                <button className="primary-action biometric-confirm-action" type="button" onClick={cancelSession}>
                  <span>返回药品列表</span>
                </button>
              ) : faceVerificationActive && manualInventory ? (
                <button className="primary-action biometric-confirm-action" type="button" disabled>
                  <ScanFace size={24} aria-hidden="true" />
                  <span>正在确认面部</span>
                </button>
              ) : faceVerificationActive ? (
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
              ) : phase === "complete" ? (
                <button
                  className="primary-action biometric-confirm-action"
                  type="button"
                  disabled={lightOffBusy}
                  onClick={acknowledgeMedicineTaken}
                >
                  {lightOffBusy ? <LoaderCircle className="spin" size={24} aria-hidden="true" /> : <CheckCircle2 size={24} aria-hidden="true" />}
                  <span>{lightOffBusy ? "正在关闭指示灯" : "我已取药，关闭指示灯"}</span>
                </button>
              ) : (
                <button
                  className="primary-action biometric-confirm-action"
                  type="button"
                  disabled={busy}
                  onClick={verifyAndOpen}
                >
                  {method === "fingerprint" ? <Fingerprint size={24} aria-hidden="true" /> : <ScanFace size={24} aria-hidden="true" />}
                  <span>{actionLabel}</span>
                </button>
              )}
            </div>
          </div>
        </div>}
      </section>
    </div>,
    document.querySelector(".kiosk-frame") || document.body
  );
}
