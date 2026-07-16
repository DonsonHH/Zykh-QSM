import React, { useEffect, useState } from "react";
import { CheckCircle2, Fingerprint, Minus, Plus, ScanFace, ShieldCheck, UserRound, X } from "lucide-react";
import { identifyFingerprint } from "../api/fingerprint.js";
import { verifyDispenseIdentity } from "../api/identity.js";
import { activateIdentity } from "../hooks/useFaceIdentity.js";
import { StrokeDrawIcon } from "./StrokeDrawIcon.jsx";

const wait = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export function DispenseConfirmModal({ medicine, identity, open, submitting, result, error, onCancel, onSubmit }) {
  const [quantity, setQuantity] = useState(1);
  const [checked, setChecked] = useState(false);
  const [method, setMethod] = useState("fingerprint");
  const [phase, setPhase] = useState("idle");
  const [verificationError, setVerificationError] = useState("");
  const [verifiedIdentity, setVerifiedIdentity] = useState(null);
  const [previewActive, setPreviewActive] = useState(false);
  const [previewRetry, setPreviewRetry] = useState(0);
  const [previewReady, setPreviewReady] = useState(false);
  const busy = phase !== "idle" || submitting;

  useEffect(() => {
    if (open) {
      setQuantity(1);
      setChecked(false);
      setMethod("fingerprint");
      setPhase("idle");
      setVerificationError("");
      setVerifiedIdentity(null);
      setPreviewActive(false);
      setPreviewRetry(0);
      setPreviewReady(false);
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
    setPreviewActive(nextMethod === "face");
    setPreviewReady(false);
  }

  async function confirmAndOpen() {
    if (!checked || busy) {
      return;
    }
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
      setVerifiedIdentity(verification.user);
      activateIdentity(verification.user);
      setPhase("opening");
      const dispense = await onSubmit({
        medicine_id: medicine.id,
        slot: medicine.slot,
        quantity,
        reason: "家庭药柜取药确认",
        confirmed_safety_notice: true,
        confirm_real_dispense: true,
        target_user_id: verification.user.id,
        target_user_name: verification.user.name,
        verification_method: method,
        verification_score: verification.score ?? null
      });
      if (dispense && dispense.ok === false) {
        throw new Error(dispense.message || "柜门未能打开");
      }
      setPhase("complete");
    } catch (requestError) {
      setPhase("idle");
      setVerificationError(requestError.message || "身份确认失败");
      if (method === "face") {
        setPreviewActive(true);
        setPreviewRetry((current) => current + 1);
      }
    }
  }

  const displayIdentity = verifiedIdentity || identity;
  const actionLabel =
    phase === "verifying"
      ? method === "fingerprint"
        ? "正在读取指纹"
        : "正在确认面部"
      : phase === "opening"
        ? "正在打开柜门"
        : phase === "complete"
          ? "柜门已打开"
          : method === "fingerprint"
            ? "按指纹确认并开柜"
            : "面部确认并开柜";

  return (
    <div className="modal-layer" role="presentation">
      <section className="dispense-modal biometric-dispense-modal" role="dialog" aria-modal="true" aria-labelledby="dispense-title">
        <button className="modal-close" type="button" onClick={onCancel} aria-label="关闭取药确认" disabled={busy}>
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
                <strong>{displayIdentity?.name || "待确认"}</strong>
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

            <label className="confirm-check" htmlFor="safety-confirmed">
              <input
                id="safety-confirmed"
                type="checkbox"
                checked={checked}
                onChange={(event) => setChecked(event.target.checked)}
              />
              <span>我已核对药品说明，并确认现场可安全开柜</span>
            </label>
          </div>

          <div className="biometric-confirm-column">
            <div className="biometric-method-toggle" aria-label="身份确认方式">
              <button type="button" className={method === "fingerprint" ? "active" : ""} onClick={() => selectMethod("fingerprint")}>
                <Fingerprint size={22} aria-hidden="true" />
                指纹
              </button>
              <button type="button" className={method === "face" ? "active" : ""} onClick={() => selectMethod("face")}>
                <ScanFace size={22} aria-hidden="true" />
                面部
              </button>
            </div>

            <div className={`biometric-stage ${method} ${phase !== "idle" ? "is-active" : ""}`}>
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
              ) : phase === "complete" ? (
                <CheckCircle2 size={88} strokeWidth={1.8} aria-hidden="true" />
              ) : (
                <StrokeDrawIcon
                  icon={method === "fingerprint" ? Fingerprint : ScanFace}
                  size={92}
                  strokeWidth={1.8}
                  mode="yoyo"
                  active={phase !== "idle"}
                />
              )}
              <strong>{method === "fingerprint" ? "请将手指放在识别模块" : "请正对摄像头"}</strong>
              <span>
                {method === "fingerprint"
                  ? "识别成功后将记录使用人并打开柜门"
                  : "未登记使用人将建立本地访客记录，便于后续核对"}
              </span>
            </div>

            <div className="biometric-identity-note">
              <UserRound size={21} aria-hidden="true" />
              <span>{displayIdentity ? `当前显示：${displayIdentity.name}，本次仍需再次确认` : "本次确认结果将写入家庭取药记录"}</span>
            </div>

            {(verificationError || error) && <p className="modal-message error">{verificationError || error}</p>}
            {result && <p className="modal-message success">{result}</p>}

            <button className="primary-action biometric-confirm-action" type="button" disabled={!checked || busy} onClick={confirmAndOpen}>
              {phase === "complete" ? <CheckCircle2 size={24} aria-hidden="true" /> : method === "fingerprint" ? <Fingerprint size={24} aria-hidden="true" /> : <ScanFace size={24} aria-hidden="true" />}
              <span>{actionLabel}</span>
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
