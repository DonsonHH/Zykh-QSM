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
import { cancelVitalsSession, loadVitalsSession, prepareQsmVitals, startVitalsSession } from "../api/qsm.js";
import { StrokeDrawIcon } from "../components/StrokeDrawIcon.jsx";

const activePhases = new Set(["starting", "waiting_finger", "stabilizing"]);
const baseMeasurementSeconds = 18;
const extendedMeasurementSeconds = 30;
const transportRetryDelayMs = 700;
const maxConsecutiveTransportFailures = 3;
const failureReasonPresentations = {
  no_protocol_frames: {
    title: "设备通信无数据",
    summary: "请检查串口连接和模块供电"
  },
  no_finger: {
    title: "未检测到手指",
    summary: "请用指腹完整覆盖传感器"
  },
  core_not_stable: {
    title: "手指信号未稳定",
    summary: "请保持手指完整覆盖并尽量不动"
  },
  spo2_not_stable: {
    title: "血氧仍未稳定",
    summary: "请保持手指不动后重试"
  },
  heart_rate_not_stable: {
    title: "心率仍未稳定",
    summary: "请保持手指不动后重试"
  },
  temperature_unavailable: {
    title: "额温未读取",
    summary: "请重新对准额温传感器"
  },
  hardware_start_timeout: {
    title: "设备启动超时",
    summary: "请检查设备连接后重试"
  },
  uart_device_missing: {
    title: "串口设备未连接",
    summary: "请检查体征模块连接和供电"
  },
  uart_busy: {
    title: "体征设备正忙",
    summary: "请等待上一轮测量结束"
  },
  session_busy: {
    title: "上一轮测量未结束",
    summary: "请稍候再开始新的测量"
  },
  worker_start_failed: {
    title: "测量服务启动失败",
    summary: "请联系值守员检查板端服务"
  },
  hardware_start_failed: {
    title: "设备启动失败",
    summary: "请检查设备连接后重试"
  },
  uart_lock_error: {
    title: "串口通信失败",
    summary: "请联系值守员检查串口服务"
  },
  uart_config_error: {
    title: "串口通信失败",
    summary: "请联系值守员检查串口服务"
  },
  uart_open_error: {
    title: "串口通信失败",
    summary: "请联系值守员检查串口服务"
  },
  uart_write_error: {
    title: "串口通信失败",
    summary: "请联系值守员检查串口服务"
  },
  uart_stop_failed: {
    title: "设备停止失败",
    summary: "请联系值守员检查体征模块"
  },
  invalid_session_id: {
    title: "测量会话无效",
    summary: "请重新开始测量"
  },
  session_not_found: {
    title: "测量会话已失效",
    summary: "请重新开始测量"
  },
  gateway_error: {
    title: "测量服务异常",
    summary: "请稍后重试或联系值守员"
  },
  transport_error: {
    title: "通信连接中断",
    summary: "请检查主机与板端连接后重试"
  }
};

export function createVitalsPollPolicy() {
  let consecutiveTransportFailures = 0;
  return {
    observe(result) {
      if (result?.failure_reason !== "transport_error") {
        consecutiveTransportFailures = 0;
        return { kind: "accept" };
      }
      consecutiveTransportFailures += 1;
      if (consecutiveTransportFailures >= maxConsecutiveTransportFailures) {
        return {
          kind: "stop",
          consecutiveFailures: consecutiveTransportFailures
        };
      }
      return {
        kind: "retry",
        delayMs: transportRetryDelayMs,
        consecutiveFailures: consecutiveTransportFailures
      };
    }
  };
}

export function normalizeVitalsStartFailure(data, fallbackMessage = "体征设备暂不可用。") {
  const structured = data && typeof data === "object" ? data : null;
  return {
    ...(structured || {}),
    ok: false,
    status: "failed",
    hardware_started: false,
    communication_status:
      structured?.communication_status || (structured ? "gateway_available" : "gateway_unreachable"),
    failure_reason:
      structured?.failure_reason || (structured ? "hardware_start_failed" : "transport_error"),
    error_message: structured?.error_message || fallbackMessage
  };
}

export function Vitals({
  onNavigate,
  returnPage = "home",
  notify,
  embedded = false,
  onComplete,
  onExit
}) {
  const [phase, setPhase] = useState("idle");
  const [sessionId, setSessionId] = useState("");
  const [result, setResult] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const requestIdRef = useRef(0);
  const completionReportedRef = useRef(false);
  const completionTimerRef = useRef(null);
  const prewarmPromiseRef = useRef(null);
  const sessionIdRef = useRef("");
  const phaseRef = useRef("idle");
  const automaticRetryRef = useRef(false);
  const automaticRetryTimerRef = useRef(null);
  const pollPolicyRef = useRef(null);
  if (!pollPolicyRef.current) pollPolicyRef.current = createVitalsPollPolicy();
  const measuring = activePhases.has(phase);
  const elapsedSeconds = Number(result?.elapsed_seconds || 0);

  const status = useMemo(() => describeVitals(result, errorMessage, phase), [errorMessage, phase, result]);
  const auxiliaryMetrics = useMemo(() => buildAuxiliaryMetrics(result), [result]);
  const hasFingerTemperature = hasReading(result?.body_temperature);
  const coreComplete = hasCoreVitals(result);

  useEffect(() => {
    ensureVitalsPrepared();
    return () => {
      window.clearTimeout(automaticRetryTimerRef.current);
      const activeSession = sessionIdRef.current;
      if (activeSession && activePhases.has(phaseRef.current)) {
        cancelVitalsSession(activeSession).catch(() => undefined);
      }
    };
  }, []);

  useEffect(() => {
    sessionIdRef.current = sessionId;
    phaseRef.current = phase;
  }, [phase, sessionId]);

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
        const pollAction = pollPolicyRef.current.observe(data);
        if (pollAction.kind === "retry") {
          setResult({ ...data, transport_retrying: true });
          setErrorMessage(data.error_message || "体征通信短暂中断，正在恢复连接。");
          timer = window.setTimeout(poll, pollAction.delayMs);
          return;
        }
        if (pollAction.kind === "stop") {
          cancelVitalsSession(sessionId).catch(() => undefined);
          applySession({ ...data, transport_retrying: false });
          return;
        }
        applySession(data);
        if (activePhases.has(data.status)) {
          timer = window.setTimeout(poll, 420);
        }
      } catch (error) {
        if (disposed) return;
        const transportFailure = {
          ok: false,
          status: "failed",
          session_id: sessionId,
          hardware_started: true,
          communication_status: "gateway_unreachable",
          failure_reason: "transport_error",
          error_message: error.message || "体征设备状态读取失败。"
        };
        const pollAction = pollPolicyRef.current.observe(transportFailure);
        if (pollAction.kind === "stop") {
          cancelVitalsSession(sessionId).catch(() => undefined);
          applySession({ ...transportFailure, transport_retrying: false });
          return;
        }
        setResult({ ...transportFailure, transport_retrying: true });
        setErrorMessage(transportFailure.error_message);
        timer = window.setTimeout(poll, pollAction.delayMs);
      }
    };
    timer = window.setTimeout(poll, 260);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
    };
  }, [phase, sessionId]);

  useEffect(() => {
    if (!embedded || phase !== "complete" || !coreComplete || completionReportedRef.current) {
      return undefined;
    }
    completionReportedRef.current = true;
    const disposition = inquiryVitalsDisposition(result);
    completionTimerRef.current = window.setTimeout(() => {
      if (disposition.kind === "complete") {
        onComplete?.(result);
        return;
      }
      onExit?.(disposition.outcome);
    }, 1800);
    return () => window.clearTimeout(completionTimerRef.current);
  }, [coreComplete, embedded, onComplete, onExit, phase, result]);

  function applySession(data) {
    setResult(data);
    setPhase(data.status || "failed");
    setErrorMessage(data.error_message || "");
    if (shouldAutomaticallyRetrySpo2(data) && !automaticRetryRef.current) {
      automaticRetryRef.current = true;
      setErrorMessage("血氧信号未稳定，正在自动重新测量，请继续保持手指不动。");
      automaticRetryTimerRef.current = window.setTimeout(
        () => handleMeasure({ automatic: true }),
        850
      );
    }
  }

  function ensureVitalsPrepared() {
    if (!prewarmPromiseRef.current) {
      prewarmPromiseRef.current = prepareQsmVitals()
        .then((data) => {
          if (!data?.hardware_started) prewarmPromiseRef.current = null;
          return data;
        })
        .catch(() => {
          prewarmPromiseRef.current = null;
          return null;
        });
    }
    return prewarmPromiseRef.current;
  }

  async function handleMeasure({ automatic = false } = {}) {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    window.clearTimeout(automaticRetryTimerRef.current);
    if (!automatic) automaticRetryRef.current = false;
    pollPolicyRef.current = createVitalsPollPolicy();
    const previousSession = sessionIdRef.current;
    setPhase("starting");
    setSessionId("");
    setResult(null);
    setErrorMessage("");
    completionReportedRef.current = false;
    try {
      if (previousSession) {
        await cancelVitalsSession(previousSession).catch(() => undefined);
      }
      let prepared = await ensureVitalsPrepared();
      if (!prepared?.hardware_started) {
        prepared = await ensureVitalsPrepared();
      }
      const data = await startVitalsSession({ replaceActive: true });
      prewarmPromiseRef.current = null;
      if (requestId !== requestIdRef.current) return;
      if (!data.hardware_started) {
        const failure = normalizeVitalsStartFailure(
          data,
          "体征设备未确认启动，请检查设备后重试。"
        );
        applySession(failure);
        notify?.(failure.error_message);
        return;
      }
      setSessionId(data.session_id);
      applySession(data);
    } catch (error) {
      if (requestId !== requestIdRef.current) return;
      const message = error.message || "体征设备暂不可用，可稍后重试。";
      applySession(normalizeVitalsStartFailure(null, message));
      notify?.(message);
    }
  }

  async function handleCancel({ exit = embedded } = {}) {
    window.clearTimeout(completionTimerRef.current);
    window.clearTimeout(automaticRetryTimerRef.current);
    requestIdRef.current += 1;
    const currentSession = sessionId;
    setPhase("cancelled");
    if (currentSession) {
      await cancelVitalsSession(currentSession).catch(() => undefined);
    }
    setSessionId("");
    setResult(null);
    setErrorMessage("");
    if (exit) onExit?.({ status: "cancelled" });
  }

  async function handleBack() {
    window.clearTimeout(completionTimerRef.current);
    if (embedded) {
      if (measuring) {
        await handleCancel({ exit: true });
        return;
      }
      onExit?.({
        status: phase === "failed" ? "failed" : "cancelled",
        error_message: errorMessage || result?.error_message || ""
      });
      return;
    }
    onNavigate?.(returnPage === "inquiry" ? "inquiry" : "home");
  }

  function handlePrimaryAction() {
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

  const Root = embedded ? "section" : "main";

  return (
    <Root className={`vitals-page ${embedded ? "embedded" : ""}`} id={embedded ? undefined : "main-content"}>
      <section className="vitals-guide-panel">
        <div className="vitals-page-heading">
          <button className="vitals-back-button" type="button" onClick={handleBack} aria-label="返回上一页" title="返回">
            <ArrowLeft size={25} aria-hidden="true" />
          </button>
          <h2>{measuring ? status.title : phase === "complete" ? "测量结果" : embedded ? "AI问询 · 体征测量" : "身体状态测量"}</h2>
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
          <button className={`primary-action vitals-primary-action ${measuring ? "cancel" : ""}`} type="button" onClick={handlePrimaryAction}>
            {measuring ? <Square size={22} fill="currentColor" aria-hidden="true" />
              : phase === "complete" && coreComplete ? <ArrowLeft size={24} aria-hidden="true" />
                : phase === "failed" || phase === "cancelled" ? <RotateCcw size={24} aria-hidden="true" />
                  : <Activity size={24} aria-hidden="true" />}
            <span>{actionLabel}</span>
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
              <div><strong>{status.summary}</strong>{status.detail ? <p>{status.detail}</p> : null}</div>
            </div>
            <HistoricalVitalsReference result={result} />
          </>
        ) : (
          <ResultPlaceholder
            phase={phase}
            elapsedSeconds={elapsedSeconds}
            targetSeconds={result?.stabilization_extended ? extendedMeasurementSeconds : baseMeasurementSeconds}
          />
        )}
      </section>
    </Root>
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

export function HistoricalVitalsReference({ result }) {
  if (!result?.historical_fallback) return null;

  const readings = [];
  if (hasReading(result.historical_heart_rate)) {
    readings.push(`${Math.round(result.historical_heart_rate)}次/分`);
  }
  if (hasReading(result.historical_spo2)) {
    readings.push(`${Math.round(result.historical_spo2)}%`);
  }
  if (hasReading(result.historical_temperature)) {
    readings.push(`${Number(result.historical_temperature).toFixed(1)}℃`);
  }
  if (!readings.length) return null;

  const measuredAt = String(result.historical_measured_at || "").replace("T", " ").slice(0, 16);
  return (
    <div className="vitals-status-card vitals-history-reference" aria-label="历史体征参考">
      <span aria-hidden="true"><HeartPulse size={24} /></span>
      <div>
        <strong>上次完整测量 · 仅供参考</strong>
        <p>{readings.join(" · ")}{measuredAt ? ` · ${measuredAt}` : ""}</p>
      </div>
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

export function describeVitals(result, errorMessage, phase) {
  if (activePhases.has(phase)) {
    if (result?.transport_retrying && result?.failure_reason === "transport_error") {
      return {
        tone: "active",
        title: "通信短暂中断",
        summary: "正在恢复当前测量",
        detail: errorMessage || result?.error_message || "正在重新连接体征服务"
      };
    }
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
  if (isDemoSpo2(result)) {
    return {
      tone: "warn",
      title: "演示结果",
      summary: "血氧为演示值，本次结果未保存",
      detail: "心率与额温来自设备，血氧仅用于现场演示。"
    };
  }
  if (hasCoreVitals(result)) {
    return { tone: "good", title: "测量完成", summary: "心率、血氧与额温已记录", detail: "" };
  }
  return { tone: "idle", title: "结果预览", summary: "准备测量", detail: "" };
}

export function inquiryVitalsDisposition(result) {
  if (isDemoSpo2(result)) {
    return {
      kind: "exit",
      outcome: {
        status: "failed",
        error_message: "血氧为演示值，本次体征未写入问询。"
      }
    };
  }
  if (result?.status !== "complete" || result?.historical_fallback) {
    return {
      kind: "exit",
      outcome: {
        status: result?.status === "cancelled" ? "cancelled" : "failed",
        error_message: result?.error_message || "本次体征测量未完成。"
      }
    };
  }
  return { kind: "complete" };
}

function isDemoSpo2(result) {
  return Boolean(result?.spo2_demo_fallback || result?.spo2_source === "demo_fallback");
}

function describeVitalsFailure(result, errorMessage) {
  const detail = errorMessage || result?.error_message || "体征设备暂不可用";
  const reasonPresentation = failureReasonPresentations[result?.failure_reason];
  if (reasonPresentation) {
    return { tone: "warn", ...reasonPresentation, detail };
  }
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

function shouldAutomaticallyRetrySpo2(result) {
  return result?.status === "failed"
    && hasReading(result?.heart_rate)
    && hasReading(result?.temperature)
    && !hasReading(result?.spo2);
}
