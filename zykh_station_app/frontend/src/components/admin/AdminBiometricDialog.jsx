import React, { useEffect, useRef, useState } from "react";
import { CheckCircle2, Fingerprint, LoaderCircle, ScanFace, X, XCircle } from "lucide-react";
import { useExitPresence } from "../../hooks/useExitPresence.js";

export function AdminBiometricDialog({ open, mode, user: currentUser, onEnroll, onProgress, onClose, onComplete }) {
  const userRef = useRef(currentUser);
  if (currentUser) userRef.current = currentUser;
  const user = currentUser || userRef.current;
  const { present, exiting } = useExitPresence(Boolean(open && currentUser));
  const [phase, setPhase] = useState("preview");
  const [message, setMessage] = useState("");
  const [previewFailed, setPreviewFailed] = useState(false);
  const [previewKey, setPreviewKey] = useState(0);
  const sessionRef = useRef(0);
  const isFace = mode === "face";
  const [event, setEvent] = useState("");

  useEffect(() => {
    if (!open) return;
    sessionRef.current += 1;
    setPhase("preview");
    setMessage("");
    setPreviewFailed(false);
    setEvent("");
    setPreviewKey((value) => value + 1);
    return () => {
      sessionRef.current += 1;
    };
  }, [open, mode, currentUser?.id]);

  if (!present || !user) return null;

  async function startEnrollment() {
    const session = sessionRef.current;
    setPhase("running");
    setMessage(isFace ? "正在采集正面与轻微侧转画面，请保持在取景框内。" : "请将同一根手指稳定按在传感器上，按提示完成采集。");
    if (isFace) await new Promise((resolve) => window.setTimeout(resolve, 450));
    try {
      const result = await onEnroll(user.id);
      if (session !== sessionRef.current) return;
      if (result?.ok === false) {
        setPhase("error");
        setMessage(result.message || "录入未完成，请检查设备后重试。");
        return;
      }
      if (!isFace && result?.job_id && result?.status === "running") {
        let current = result;
        setEvent(current.event || "place_finger_first");
        setMessage(current.message || "请将手指完整覆盖识别区域。");
        while (session === sessionRef.current && current?.status === "running") {
          await new Promise((resolve) => window.setTimeout(resolve, 350));
          current = await onProgress(user.id, result.job_id);
          if (session !== sessionRef.current) return;
          setEvent(current?.event || "");
          setMessage(current?.message || "正在采集指纹特征。");
        }
        if (current?.ok === false || current?.status !== "enrolled") {
          setPhase("error");
          setMessage(current?.message || "录入未完成，请检查设备后重试。");
          return;
        }
        setPhase("success");
        setMessage(current.message || "指纹录入完成。");
        onComplete?.(current);
        return;
      }
      setPhase("success");
      setMessage(result?.message || `${isFace ? "人脸" : "指纹"}录入完成。`);
      onComplete?.(result);
    } catch (error) {
      if (session !== sessionRef.current) return;
      setPhase("error");
      setMessage(error.message || "录入失败，请检查设备连接后重试。");
    }
  }

  const canClose = phase !== "running";
  return (
    <div className={`admin-dialog-backdrop biometric${exiting ? " is-exiting" : ""}`} role="presentation" onMouseDown={(event) => event.target === event.currentTarget && open && canClose && onClose()}>
      <section className="admin-biometric-dialog" role="dialog" aria-modal="true" aria-labelledby="admin-biometric-title">
        <header>
          <div>
            <span>{isFace ? "人脸录入" : "指纹录入"}</span>
            <h3 id="admin-biometric-title">为 {user.name} 建立识别信息</h3>
          </div>
          <button type="button" className="admin-icon-button" onClick={onClose} disabled={!canClose} aria-label="关闭录入窗口"><X size={20} /></button>
        </header>

        <div className={`admin-biometric-stage ${isFace ? "face" : "fingerprint"} ${phase}`}>
          {isFace && phase === "preview" ? (
            <div className="admin-face-enroll-preview">
              {!previewFailed ? (
                <img
                  key={previewKey}
                  src={`/api/camera/stream?admin-enroll=${previewKey}`}
                  alt="人脸录入实时预览"
                  onError={() => setPreviewFailed(true)}
                />
              ) : (
                <button type="button" onClick={() => { setPreviewFailed(false); setPreviewKey((value) => value + 1); }}>
                  <ScanFace size={52} />
                  <strong>预览暂不可用</strong>
                  <span>点击重新连接摄像头</span>
                </button>
              )}
              <span className="admin-face-guide" aria-hidden="true" />
            </div>
          ) : null}

          {!isFace && phase === "preview" ? (
            <div className="admin-fingerprint-guide">
              <span className="fingerprint-rings"><Fingerprint size={82} strokeWidth={1.7} /></span>
              <strong>使用常用手指完成录入</strong>
              <p>首次采集后请完全移开手指，再按提示放置同一根手指。</p>
            </div>
          ) : null}

          {phase === "running" ? (
            <div className={`admin-biometric-progress ${event || "starting"}`}>
              <span>{isFace ? <ScanFace size={70} /> : <Fingerprint size={70} />}</span>
              <LoaderCircle className="admin-spin" size={30} />
              <strong>{isFace ? "正在采集人脸特征" : event === "remove_finger" ? "请完全移开手指" : event === "place_same_finger_second" ? "请再次放置同一根手指" : "请放置手指"}</strong>
              <p>{message}</p>
            </div>
          ) : null}

          {phase === "success" ? (
            <div className="admin-biometric-result success"><CheckCircle2 size={64} /><strong>录入成功</strong><p>{message}</p></div>
          ) : null}
          {phase === "error" ? (
            <div className="admin-biometric-result error"><XCircle size={64} /><strong>录入未完成</strong><p>{message}</p></div>
          ) : null}
        </div>

        <footer>
          {phase === "preview" ? <button type="button" className="admin-button secondary" onClick={onClose}>取消</button> : null}
          {phase === "preview" ? <button type="button" className="admin-button primary" onClick={startEnrollment}>开始录入</button> : null}
          {phase === "error" ? <button type="button" className="admin-button secondary" onClick={() => { setPhase("preview"); setMessage(""); setPreviewFailed(false); setPreviewKey((value) => value + 1); }}>重新准备</button> : null}
          {phase === "success" ? <button type="button" className="admin-button primary" onClick={onClose}>完成</button> : null}
        </footer>
      </section>
    </div>
  );
}
