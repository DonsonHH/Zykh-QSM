import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowLeft,
  Fingerprint,
  Gauge,
  HeartPulse,
  MoveVertical,
  RotateCcw,
  ScanFace,
  ShieldCheck,
  Square,
  Thermometer,
  Waves,
  Wind
} from "lucide-react";
import { cancelVitalsSession, loadVitalsSession, startVitalsSession } from "../api/qsm.js";
import { attachInquiryVitals } from "../api/inquiry.js";
import { StrokeDrawIcon } from "../components/StrokeDrawIcon.jsx";

const activePhases = new Set(["starting", "waiting_finger", "stabilizing"]);
const baseMeasurementSeconds = 18;
const extendedMeasurementSeconds = 30;

export function Vitals({ onNavigate, context = {}, notify }) {
  const [phase, setPhase] = useState("idle");
  const [sessionId, setSessionId] = useState("");
  const [result, setResult] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [returningToInquiry, setReturningToInquiry] = useState(false);
  const requestIdRef = useRef(0);
  const attachedResultRef = useRef("");
  const autoStartedRef = useRef(false);
  const returnPage = context.returnTo || "home";
  const measuring = activePhases.has(phase);
  const elapsedSeconds = Number(result?.elapsed_seconds || 0);

  const status = useMemo(() => describeVitals(result, errorMessage, phase), [errorMessage, phase, result]);
  const auxiliaryMetrics = useMemo(() => buildAuxiliaryMetrics(result), [result]);
  const hasFingerTemperature = hasReading(result?.body_temperature);
  const coreComplete = hasCoreVitals(result);

  useEffect(() => {
    if (!sessionId || !activePhases.has(phase)) {
      return undefined;
    }
    let disposed = false;
    let timer = 0;
    const poll = async () => {
      try {
        const data = await loadVitalsSession(sessionId);
        if (disposed) return;
        applySession(data);
        if (activePhases.has(data.status)) {
          timer = window.setTimeout(poll, 420);
        } else if (isTerminalPhase(data.status)) {
          await attachResultToInquiry(data);
        }
      } catch (error) {
        if (disposed) return;
        const message = error.message || "体征设备状态读取失败，请重新测量。";
        setErrorMessage(message);
        setPhase("failed");
        await attachResultToInquiry({
          status: "failed",
          session_id: sessionId,
          error_message: message,
          measured_at: new Date().toISOString()
        });
      }
    };
    timer = window.setTimeout(poll, 260);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
    };
  }, [phase, sessionId]);

  useEffect(() => {
    if (!context.autoStart || !context.inquirySessionId || autoStartedRef.current) {
      return undefined;
    }
    autoStartedRef.current = true;
    const timer = window.setTimeout(() => handleMeasure(), 240);
    return () => window.clearTimeout(timer);
  }, [context.autoStart, context.inquirySessionId]);

  function applySession(data) {
    setResult(data);
    setPhase(data.status || "failed");
    setErrorMessage(data.error_message || "");
  }

  async function handleMeasure() {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setPhase("starting");
    setSessionId("");
    setResult(null);
    setErrorMessage("");
    try {
      const data = await startVitalsSession();
      if (requestId !== requestIdRef.current) return;
      if (!data.hardware_started) {
        throw new Error(data.error_message || "体征设备未确认启动，请检查设备后重试。");
      }
      setSessionId(data.session_id);
      applySession(data);
      if (isTerminalPhase(data.status)) {
        await attachResultToInquiry(data);
      }
    } catch (error) {
      if (requestId !== requestIdRef.current) return;
      const message = error.message || "体征设备暂不可用，可稍后重试。";
      setErrorMessage(message);
      setPhase("failed");
      notify?.(message);
      await attachResultToInquiry({
        status: "failed",
        session_id: sessionId,
        error_message: message,
        measured_at: new Date().toISOString()
      });
    }
  }

  async function handleCancel() {
    requestIdRef.current += 1;
    const currentSession = sessionId;
    let cancelled = {
      status: "cancelled",
      session_id: currentSession,
      error_message: "用户取消了本次体征测量。",
      measured_at: new Date().toISOString()
    };
    if (currentSession) {
      cancelled = await cancelVitalsSession(currentSession).catch(() => cancelled);
    }
    setPhase("cancelled");
    setSessionId("");
    setResult(cancelled);
    setErrorMessage(cancelled.error_message || "");
    await attachResultToInquiry(cancelled);
  }

  function handleBack() {
    if (measuring) {
      handleCancel();
      return;
    }
    onNavigate(returnPage === "inquiry" ? "inquiry" : "home");
  }

  function handlePrimaryAction() {
    if (returningToInquiry) return;
    if (measuring) {
      handleCancel();
      return;
    }
    if (phase === "complete" && coreComplete) {
      handleBack();
      return;
    }
    handleMeasure();
  }

  const actionLabel = measuring
    ? "取消测量"
    : phase === "complete" && coreComplete
      ? returnPage === "inquiry" ? "返回问询" : "返回上一页"
      : phase === "failed" || phase === "cancelled" ? "重新测量" : "开始测量";

  async function attachResultToInquiry(data) {
    if (!context.inquirySessionId) return false;
    const status = normalizeInquiryMeasurementStatus(data);
    const key = `${data?.session_id || "no-session"}:${status}`;
    if (attachedResultRef.current === key) return true;
    attachedResultRef.current = key;
    setReturningToInquiry(true);
    try {
      const updated = await attachInquiryVitals(
        context.inquirySessionId,
        buildInquiryVitalsPayload(data, status)
      );
      if (updated.next_action === "measure_vitals" && status !== "cancelled") {
        notify?.("本次信号未稳定，正在按问询需要重新测量");
        attachedResultRef.current = "";
        setReturningToInquiry(false);
        setSessionId("");
        setResult(null);
        setErrorMessage("");
        setPhase("idle");
        window.setTimeout(() => handleMeasure(), 760);
        return true;
      }
      notify?.(
        status === "complete"
          ? "体征结果已合并到本次问询"
          : "本次测量情况已返回问询，可继续说明症状"
      );
      window.setTimeout(() => onNavigate("inquiry", { transition: "backward" }), 420);
      return true;
    } catch (error) {
      attachedResultRef.current = "";
      const message = error.message || "体征信息未能写入本次问询，请重试";
      setErrorMessage(message);
      setPhase("failed");
      setReturningToInquiry(false);
      notify?.(message);
      return false;
    }
  }

  return (
    <main className="vitals-page" id="main-content">
      <section className="vitals-guide-panel">
        <div className="vitals-page-heading">
          <button className="vitals-back-button" type="button" onClick={handleBack} aria-label="返回上一页" title="返回">
            <ArrowLeft size={25} aria-hidden="true" />
          </button>
          <h2>{measuring ? status.title : phase === "complete" ? "测量结果" : "身体状态测量"}</h2>
          {context.reason ? (
            <div className="vitals-inquiry-purpose" role="note">
              <ShieldCheck size={20} aria-hidden="true" />
              <span><strong>本次测量</strong>{context.reason}</span>
            </div>
          ) : null}
        </div>

        <div className={`vitals-visual-guide ${measuring ? "measuring" : phase}`}>
          <article className="vitals-pose-card forehead">
            <div className="vitals-pose-graphic" aria-hidden="true">
              <span className="vitals-sensor-cap" />
              {measuring ? <StrokeDrawIcon icon={ScanFace} size={76} strokeWidth={2} mode="yoyo" /> : <ScanFace size={76} />}
              <span className="vitals-distance-mark"><MoveVertical size={22} />20cm</span>
            </div>
            <div className="vitals-pose-label">
              <span className="vitals-pose-icon forehead" aria-hidden="true"><Thermometer size={24} /></span>
              <strong>额温</strong>
            </div>
          </article>

          <article className="vitals-pose-card fingertip">
            <div className="vitals-pose-graphic" aria-hidden="true">
              {measuring ? <StrokeDrawIcon icon={Fingerprint} size={78} strokeWidth={2} mode="yoyo" /> : <Fingerprint size={78} />}
            </div>
            <div className="vitals-pose-label">
              <span className="vitals-pose-icon fingertip" aria-hidden="true"><HeartPulse size={24} /></span>
              <strong>心率 · 血氧</strong>
            </div>
          </article>
        </div>

        <div className="vitals-action-row">
          <button className={`primary-action vitals-primary-action ${measuring ? "cancel" : ""}`} type="button" onClick={handlePrimaryAction} disabled={returningToInquiry}>
            {measuring ? <Square size={22} fill="currentColor" aria-hidden="true" />
              : phase === "complete" && coreComplete ? <ArrowLeft size={24} aria-hidden="true" />
                : phase === "failed" || phase === "cancelled" ? <RotateCcw size={24} aria-hidden="true" />
                  : <Activity size={24} aria-hidden="true" />}
            <span>{returningToInquiry ? "正在返回问询" : actionLabel}</span>
          </button>
        </div>
      </section>

      <section className={`vitals-result-panel ${status.tone} ${auxiliaryMetrics.length ? "has-reference" : "core-only"}`} aria-label="体征测量结果">
        <div className="vitals-result-heading">
          <span aria-hidden="true"><Thermometer size={34} /></span>
          <h2 aria-live="polite">{status.title}</h2>
        </div>

        {result && !measuring ? (
          <>
            <div className={`vitals-metric-grid ${hasFingerTemperature ? "four" : "three"}`}>
              <Metric icon={HeartPulse} label="心率" value={formatMetric(result.heart_rate, "次/分", 0)} tone="heart" primary />
              <Metric icon={Activity} label="血氧" value={formatMetric(result.spo2, "%", 0)} tone="oxygen" primary />
              <Metric icon={Thermometer} label="额温" value={formatMetric(result.temperature, "℃", 1)} tone="forehead" />
              {hasFingerTemperature ? <Metric icon={Fingerprint} label="指温参考" value={formatMetric(result.body_temperature, "℃", 2)} tone="finger" /> : null}
            </div>
            {auxiliaryMetrics.length ? (
              <div className={`vitals-reference-grid count-${auxiliaryMetrics.length}`} aria-label="本次读取到的辅助体征">
                {auxiliaryMetrics.map(({ icon, label, value }) => <ReferenceMetric key={label} icon={icon} label={label} value={value} />)}
              </div>
            ) : null}
            <div className="vitals-status-card">
              <span aria-hidden="true"><ShieldCheck size={24} /></span>
              <div><strong>{status.summary}</strong>{status.tone === "warn" ? <p>{status.detail}</p> : null}</div>
            </div>
          </>
        ) : (
          <ResultPlaceholder
            phase={phase}
            elapsedSeconds={elapsedSeconds}
            targetSeconds={result?.stabilization_extended ? extendedMeasurementSeconds : baseMeasurementSeconds}
          />
        )}
      </section>
    </main>
  );
}

function ResultPlaceholder({ phase, elapsedSeconds, targetSeconds }) {
  const measuring = activePhases.has(phase);
  const progress = Math.min(0.96, Math.max(0.04, elapsedSeconds / targetSeconds));
  return (
    <div className={`vitals-result-placeholder ${measuring ? "measuring" : "idle"}`} role="status" aria-label={measuring ? stageTitle(phase) : "等待开始体征测量"}>
      <div className={`vitals-result-visual ${measuring ? "is-measuring" : ""}`} aria-hidden="true">
        <span className="vitals-result-heart"><HeartPulse size={132} strokeWidth={1.65} /></span>
      </div>
      {measuring ? <span className="vitals-measure-progress" aria-hidden="true"><i style={{ transform: `scaleX(${progress})` }} /></span> : null}
    </div>
  );
}

function Metric({ icon: Icon, label, value, tone, primary = false }) {
  return <article className={`vitals-metric ${tone} ${primary ? "primary" : ""}`}><span className="vitals-metric-icon" aria-hidden="true"><Icon size={25} /></span><span className="vitals-metric-label">{label}</span><strong>{value}</strong></article>;
}

function ReferenceMetric({ icon: Icon, label, value }) {
  return <article className="vitals-reference-metric"><Icon size={20} aria-hidden="true" /><span>{label}</span><strong>{value}</strong></article>;
}

function formatMetric(value, unit, fractionDigits = 0) {
  if (!hasReading(value)) return "未读取";
  return `${Number(value).toFixed(fractionDigits)}${unit}`;
}

function buildAuxiliaryMetrics(result) {
  if (!result) return [];
  const metrics = [];
  if (hasReading(result.systolic_pressure) && hasReading(result.diastolic_pressure)) {
    metrics.push({ icon: Gauge, label: "血压", value: `${Math.round(result.systolic_pressure)}/${Math.round(result.diastolic_pressure)}` });
  }
  if (hasReading(result.respiratory_rate)) metrics.push({ icon: Wind, label: "呼吸", value: `${Math.round(result.respiratory_rate)}次/分` });
  if (hasReading(result.hrv_sdnn)) metrics.push({ icon: Waves, label: "HRV", value: `${Math.round(result.hrv_sdnn)}ms` });
  return metrics;
}

function describeVitals(result, errorMessage, phase) {
  if (activePhases.has(phase)) {
    if (Number(result?.heart_rate_frame_count || 0) > 0 && Number(result?.spo2_frame_count || 0) === 0) {
      return { tone: "active", title: "血氧正在稳定", summary: "心率信号已读取，请保持手指不动", detail: "" };
    }
    if (Number(result?.spo2_frame_count || 0) > 0 && Number(result?.heart_rate_frame_count || 0) === 0) {
      return { tone: "active", title: "心率正在稳定", summary: "血氧信号已读取，请保持手指不动", detail: "" };
    }
    if (Number(result?.elapsed_seconds || 0) < 10) {
      return { tone: "active", title: "传感器预热中", summary: "请保持手指与额头位置不动", detail: "" };
    }
    if (phase === "waiting_finger") {
      return { tone: "active", title: "等待手指信号", summary: "请用指腹完整覆盖传感器", detail: "" };
    }
    return { tone: "active", title: stageTitle(phase), summary: "核心体征采集中", detail: "" };
  }
  if (errorMessage || phase === "failed" || result?.ok === false) {
    return describeVitalsFailure(result, errorMessage);
  }
  if (hasCoreVitals(result)) {
    return { tone: "good", title: "测量完成", summary: "心率、血氧与额温已记录", detail: "" };
  }
  return { tone: "idle", title: "结果预览", summary: "准备测量", detail: "" };
}

function describeVitalsFailure(result, errorMessage) {
  const detail = errorMessage || result?.error_message || "体征设备暂不可用";
  if (result?.hardware_started === false) {
    return { tone: "warn", title: "设备未启动", summary: "请检查体征设备", detail };
  }
  if (!hasReading(result?.heart_rate) && !hasReading(result?.spo2)) {
    return { tone: "warn", title: "手指信号未稳定", summary: "请用指腹完整覆盖传感器", detail };
  }
  if (!hasReading(result?.spo2)) {
    return { tone: "warn", title: "血氧仍在稳定", summary: "请保持手指不动后重试", detail };
  }
  if (!hasReading(result?.heart_rate)) {
    return { tone: "warn", title: "心率仍在稳定", summary: "请保持手指不动后重试", detail };
  }
  if (!hasReading(result?.temperature)) {
    return { tone: "warn", title: "额温未读取", summary: "请重新对准额温传感器", detail };
  }
  return { tone: "warn", title: "本次未完成", summary: "请重新测量", detail };
}

function stageTitle(phase) {
  return {
    starting: "正在启动设备",
    waiting_finger: "请放稳手指",
    stabilizing: "正在稳定读数"
  }[phase] || "正在测量";
}

function hasReading(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0;
}

function hasCoreVitals(result) {
  return hasReading(result?.heart_rate) && hasReading(result?.spo2) && hasReading(result?.temperature);
}

function isTerminalPhase(phase) {
  return ["complete", "failed", "cancelled"].includes(phase);
}

function normalizeInquiryMeasurementStatus(data) {
  if (data?.status === "cancelled") return "cancelled";
  if (data?.status === "failed" || data?.ok === false) return "failed";
  return hasCoreVitals(data) && !data?.partial ? "complete" : "partial";
}

function buildInquiryVitalsPayload(data, status) {
  return {
    measurement_session_id: data?.session_id || "",
    status,
    temperature: data?.temperature ?? null,
    heart_rate: data?.heart_rate ?? null,
    spo2: data?.spo2 ?? null,
    body_temperature: data?.body_temperature ?? null,
    systolic_pressure: data?.systolic_pressure ?? null,
    diastolic_pressure: data?.diastolic_pressure ?? null,
    respiratory_rate: data?.respiratory_rate ?? null,
    hrv_sdnn: data?.hrv_sdnn ?? null,
    hrv_rmssd: data?.hrv_rmssd ?? null,
    rr_interval: data?.rr_interval ?? null,
    microcirculation: data?.microcirculation ?? null,
    fatigue: data?.fatigue ?? null,
    ambient_temperature: data?.ambient_temperature ?? null,
    quality: data?.quality || "",
    reference_ready: data?.reference_ready ?? null,
    finger_detected: data?.finger_detected ?? null,
    sample_count: data?.sample_count ?? null,
    valid_frame_count: data?.valid_frame_count ?? null,
    contact_frame_count: data?.contact_frame_count ?? null,
    heart_rate_frame_count: data?.heart_rate_frame_count ?? null,
    spo2_frame_count: data?.spo2_frame_count ?? null,
    stabilization_extended: data?.stabilization_extended ?? null,
    partial: status === "partial",
    source: data?.source || "",
    error_message: data?.error_message || "",
    measured_at: data?.measured_at || data?.updated_at || new Date().toISOString()
  };
}
