import React, { useEffect, useRef, useState } from "react";
import { CheckCircle2, Fingerprint, Minus, Plus, ScanFace, ShieldCheck, X } from "lucide-react";
import { identifyFingerprint } from "../api/fingerprint.js";
import { verifyDispenseIdentity } from "../api/identity.js";
import { activateIdentity } from "../hooks/useFaceIdentity.js";
import { StrokeDrawIcon } from "./StrokeDrawIcon.jsx";

const wait = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export function DispenseConfirmModal({ medicine, open, submitting, result, error, onCancel, onSubmit }) {
  const [quantity, setQuantity] = useState(1);
  const [method, setMethod] = useState("fingerprint");
  const [phase, setPhase] = useState("idle");
  const [verificationError, setVerificationError] = useState("");
  const [verifiedIdentity, setVerifiedIdentity] = useState(null);
  const [verificationMeta, setVerificationMeta] = useState(null);
  const [previewActive, setPreviewActive] = useState(false);
  const [previewRetry, setPreviewRetry] = useState(0);
  const [previewReady, setPreviewReady] = useState(false);
  const sessionRef = useRef(0);
  const busy = ["verifying", "opening"].includes(phase) || submitting;

  useEffect(() => {
    if (open) {
      sessionRef.current += 1;
      setQuantity(1);
      setMethod("fingerprint");
      setPhase("idle");
      setVerificationError("");
      setVerifiedIdentity(null);
      setVerificationMeta(null);
      setPreviewActive(false);
      setPreviewRetry(0);
      setPreviewReady(false);
    } else {
      sessionRef.current += 1;
    }
  }, [medicine?.id, open]);

  if (!open || !medicine) {
    return null;
  }

  function changeQuantity(nextQuantity) {
    setQuantity(Math.max(1, Math.min(30, nextQuantity)));
  }

  function selectMethod(nextMethod) {
    if (busy || nextMethod === method) {
      return;
    }
    setMethod(nextMethod);
    setVerificationError("");
    setVerifiedIdentity(null);
    setVerificationMeta(null);
    setPreviewActive(nextMethod === "face");
    setPreviewReady(false);
  }

  async function verifyIdentity() {
    if (busy || ["recognized", "complete"].includes(phase)) {
      return;
    }
    const session = sessionRef.current;
    setVerificationError("");
    setPhase("verifying");
    try {
      let verification;
      if (method === "fingerprint") {
        verification = await identifyFingerprint(45);
      } else {
        setPreviewActive(false);
        setPreviewReady(false);
        await wait(450);
        verification = await verifyDispenseIdentity(18);
      }
      if (!verification?.ok || !verification?.user) {
        throw new Error(verification?.error_message || verification?.message || "身份确认未完成");
      }
      if (session !== sessionRef.current) {
        return;
      }
      setVerifiedIdentity(verification.user);
      setVerificationMeta(verification);
      activateIdentity(verification.user);
      setPhase("recognized");
    } catch (requestError) {
      setPhase("idle");
      setVerificationError(requestError.message || "身份确认失败");
      if (method === "face") {
        setPreviewActive(true);
        setPreviewRetry((current) => current + 1);
      }
    }
  }

  async function confirmAndOpen() {
    if (phase !== "recognized" || busy || !verifiedIdentity) {
      return;
    }
    const session = sessionRef.current;
    setVerificationError("");
    setPhase("opening");
    try {
      const dispense = await onSubmit({
        medicine_id: medicine.id,
        slot: medicine.slot,
        quantity,
        reason: "家庭药柜取药确认",
        confirmed_safety_notice: true,
        confirm_real_dispense: true,
        target_user_id: verifiedIdentity.id,
        target_user_name: verifiedIdentity.name,
        verification_method: method,
        verification_score: verificationMeta?.score ?? null
      });
      if (dispense && dispense.ok === false) {
        throw new Error(dispense.message || "柜门未能打开");
      }
      if (session === sessionRef.current) {
        setPhase("complete");
      }
    } catch (requestError) {
      if (session === sessionRef.current) {
        setPhase("recognized");
        setVerificationError(requestError.message || "柜门未能打开");
      }
    }
  }

  function cancelSession() {
    sessionRef.current += 1;
    setPreviewActive(false);
    onCancel();
  }

  const stageTitle =
    phase === "verifying"
      ? method === "fingerprint" ? "正在读取指纹" : "正在识别面部"
      : phase === "recognized"
        ? `${verifiedIdentity?.name || "使用人"}，身份已确认`
        : phase === "opening"
          ? "正在打开柜门"
          : phase === "complete"
            ? "柜门已打开"
            : method === "fingerprint" ? "请将手指放在识别模块" : "请正对摄像头";
  const stageDescription =
    phase === "recognized"
      ? verificationMeta?.new_guest
        ? "已建立本地访客档案，请核对身份后确认开柜"
        : verificationMeta?.match_count
          ? `第 ${verificationMeta.match_count} 次身份确认，请核对姓名后开柜`
          : "请核对姓名后确认开柜"
      : phase === "opening"
        ? `${medicine.hardware_slot || medicine.slot} 号柜即将开启`
        : phase === "complete"
          ? "请取出药品并关闭柜门"
          : method === "fingerprint"
            ? "识别成功后会显示使用人，请确认姓名后再打开柜门"
            : "陌生使用人会在本机留存面部特征，便于后续核对";
  const actionLabel =
    phase === "verifying"
      ? method === "fingerprint"
        ? "正在读取指纹"
        : "正在确认面部"
      : phase === "opening"
        ? "正在打开柜门"
        : phase === "recognized"
          ? "确认取药并开柜"
        : phase === "complete"
          ? "柜门已打开"
          : method === "fingerprint"
            ? "开始指纹确认"
            : "开始面部确认";

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
                <strong>{verifiedIdentity?.name || "等待确认"}</strong>
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
              <button type="button" className={method === "fingerprint" ? "active" : ""} onClick={() => selectMethod("fingerprint")} disabled={busy}>
                <Fingerprint size={22} aria-hidden="true" />
                指纹
              </button>
              <button type="button" className={method === "face" ? "active" : ""} onClick={() => selectMethod("face")} disabled={busy}>
                <ScanFace size={22} aria-hidden="true" />
                面部
              </button>
            </div>

            <div className={`biometric-stage ${method} ${phase} ${phase !== "idle" ? "is-active" : ""}`}>
              {method === "face" && previewActive && phase === "idle" ? (
                <>
                  <img
                    className={previewReady ? "ready" : "loading"}
                    src={`/api/camera/stream?identity=${previewRetry}`}
                    alt=""
                    onLoad={() => setPreviewReady(true)}
                    onError={() => {
                      setPreviewReady(false);
                      window.setTimeout(() => setPreviewRetry((current) => current + 1), 1200);
                    }}
                  />
                  {!previewReady && <StrokeDrawIcon icon={ScanFace} size={82} strokeWidth={1.8} mode="yoyo" active />}
                </>
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
              <strong>{stageTitle}</strong>
              <span>{stageDescription}</span>
            </div>

            {(verificationError || error) && <p className="modal-message error">{verificationError || error}</p>}
            {result && <p className="modal-message success">{result}</p>}

            <button
              className="primary-action biometric-confirm-action"
              type="button"
              disabled={busy || phase === "complete"}
              onClick={phase === "recognized" ? confirmAndOpen : verifyIdentity}
            >
              {phase === "complete" ? <CheckCircle2 size={24} aria-hidden="true" /> : method === "fingerprint" ? <Fingerprint size={24} aria-hidden="true" /> : <ScanFace size={24} aria-hidden="true" />}
              <span>{actionLabel}</span>
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
