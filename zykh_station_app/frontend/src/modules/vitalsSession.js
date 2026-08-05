import { useEffect, useRef, useState } from "react";
import { loadVitalsSession, prepareQsmVitals, startVitalsSession } from "../api/qsm.js";
import {
  cancelVitalsSessionNow,
  createVitalsPollPolicy,
  normalizeVitalsStartFailure
} from "../adapters/vitalsSessionAdapter.js";


const activePhases = new Set(["starting", "waiting_finger", "stabilizing"]);

export function isVitalsSessionActive(phase) {
  return activePhases.has(phase);
}

export function hasVitalsReading(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0;
}

export function hasCoreVitals(result) {
  return hasVitalsReading(result?.heart_rate)
    && hasVitalsReading(result?.spo2)
    && hasVitalsReading(result?.temperature);
}

export function isDemoSpo2(result) {
  return Boolean(result?.spo2_demo_fallback || result?.spo2_source === "demo_fallback");
}

export function vitalsTemperaturePresentation(result) {
  const fingertipFallback = result?.temperature_source === "uart8_fingertip_reference";
  return {
    label: fingertipFallback ? "指温参考" : "额温",
    showSeparateFingerTemperature: hasVitalsReading(result?.body_temperature) && !fingertipFallback
  };
}

export function shouldAutomaticallyRetrySpo2(result) {
  return result?.status === "failed"
    && hasVitalsReading(result?.heart_rate)
    && hasVitalsReading(result?.temperature)
    && !hasVitalsReading(result?.spo2);
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

export function useVitalsSession({
  embedded = false,
  notify,
  onComplete,
  onExit
} = {}) {
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

  const measuring = isVitalsSessionActive(phase);
  const elapsedSeconds = Number(result?.elapsed_seconds || 0);
  const coreComplete = hasCoreVitals(result);

  function requestBoardCancellation(activeSession) {
    const action = pollPolicyRef.current.requestCancel(activeSession);
    if (action.kind !== "stop") return Promise.resolve();
    return cancelVitalsSessionNow(action.sessionId);
  }

  useEffect(() => {
    ensurePrepared();
    return () => {
      window.clearTimeout(automaticRetryTimerRef.current);
      const activeSession = sessionIdRef.current;
      if (activeSession && isVitalsSessionActive(phaseRef.current)) {
        requestBoardCancellation(activeSession);
      }
    };
  }, []);

  useEffect(() => {
    sessionIdRef.current = sessionId;
    phaseRef.current = phase;
  }, [phase, sessionId]);

  useEffect(() => {
    if (!sessionId || !isVitalsSessionActive(phase)) {
      return undefined;
    }
    let disposed = false;
    let timer = 0;
    const poll = async () => {
      try {
        const data = await loadVitalsSession(sessionId);
        if (disposed) return;
        const pollAction = pollPolicyRef.current.observe(data);
        if (pollAction.kind === "ignore") return;
        if (pollAction.kind === "retry") {
          setResult({ ...data, transport_retrying: true });
          setErrorMessage(data.error_message || "体征通信短暂中断，正在恢复连接。");
          timer = window.setTimeout(poll, pollAction.delayMs);
          return;
        }
        if (pollAction.kind === "stop") {
          cancelVitalsSessionNow(pollAction.sessionId);
          applySession({ ...data, transport_retrying: false });
          return;
        }
        applySession(data);
        if (isVitalsSessionActive(data.status)) {
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
        if (pollAction.kind === "ignore") return;
        if (pollAction.kind === "stop") {
          cancelVitalsSessionNow(pollAction.sessionId);
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
    phaseRef.current = data.status || "failed";
    setPhase(phaseRef.current);
    setErrorMessage(data.error_message || "");
    if (shouldAutomaticallyRetrySpo2(data) && !automaticRetryRef.current) {
      automaticRetryRef.current = true;
      setErrorMessage("血氧信号未稳定，正在自动重新测量，请继续保持手指不动。");
      automaticRetryTimerRef.current = window.setTimeout(
        () => measure({ automatic: true }),
        850
      );
    }
  }

  function ensurePrepared() {
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

  async function measure({ automatic = false } = {}) {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    window.clearTimeout(automaticRetryTimerRef.current);
    if (!automatic) automaticRetryRef.current = false;
    const previousSession = sessionIdRef.current;
    const previousCancellation = previousSession
      ? requestBoardCancellation(previousSession)
      : Promise.resolve();
    pollPolicyRef.current = createVitalsPollPolicy();
    sessionIdRef.current = "";
    setPhase("starting");
    setSessionId("");
    setResult(null);
    setErrorMessage("");
    completionReportedRef.current = false;
    try {
      await previousCancellation;
      let prepared = await ensurePrepared();
      if (!prepared?.hardware_started) {
        prepared = await ensurePrepared();
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
      pollPolicyRef.current = createVitalsPollPolicy(data.session_id);
      sessionIdRef.current = data.session_id;
      setSessionId(data.session_id);
      applySession(data);
    } catch (error) {
      if (requestId !== requestIdRef.current) return;
      const message = error.message || "体征设备暂不可用，可稍后重试。";
      applySession(normalizeVitalsStartFailure(null, message));
      notify?.(message);
    }
  }

  async function cancel({ exit = embedded } = {}) {
    window.clearTimeout(completionTimerRef.current);
    window.clearTimeout(automaticRetryTimerRef.current);
    requestIdRef.current += 1;
    const currentSession = sessionIdRef.current || sessionId;
    sessionIdRef.current = "";
    phaseRef.current = "cancelled";
    setPhase("cancelled");
    if (currentSession) {
      await requestBoardCancellation(currentSession);
    }
    setSessionId("");
    setResult(null);
    setErrorMessage("");
    if (exit) onExit?.({ status: "cancelled" });
  }

  async function exitEmbedded() {
    window.clearTimeout(completionTimerRef.current);
    if (measuring) {
      await cancel({ exit: true });
      return;
    }
    onExit?.({
      status: phase === "failed" ? "failed" : "cancelled",
      error_message: errorMessage || result?.error_message || ""
    });
  }

  return {
    phase,
    result,
    errorMessage,
    measuring,
    elapsedSeconds,
    coreComplete,
    measure,
    cancel,
    exitEmbedded
  };
}
