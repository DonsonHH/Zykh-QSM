import { cancelVitalsSession } from "../api/qsm.js";


const transportRetryDelayMs = 700;
const maxConsecutiveTransportFailures = 3;

export function createVitalsPollPolicy(sessionId = "") {
  let consecutiveTransportFailures = 0;
  let stopRequested = false;
  return {
    observe(result) {
      if (!sessionId || result?.session_id !== sessionId) {
        return { kind: "ignore", reason: "stale_session" };
      }
      if (stopRequested) {
        return { kind: "ignore", reason: "stop_already_requested" };
      }
      if (result?.failure_reason !== "transport_error") {
        consecutiveTransportFailures = 0;
        return { kind: "accept" };
      }
      consecutiveTransportFailures += 1;
      if (consecutiveTransportFailures >= maxConsecutiveTransportFailures) {
        stopRequested = true;
        return {
          kind: "stop",
          sessionId,
          consecutiveFailures: consecutiveTransportFailures
        };
      }
      return {
        kind: "retry",
        sessionId,
        delayMs: transportRetryDelayMs,
        consecutiveFailures: consecutiveTransportFailures
      };
    },
    requestCancel(requestedSessionId) {
      if (!sessionId || requestedSessionId !== sessionId) {
        return { kind: "ignore", reason: "stale_session" };
      }
      if (stopRequested) {
        return { kind: "ignore", reason: "stop_already_requested" };
      }
      stopRequested = true;
      return { kind: "stop", sessionId };
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

export function cancelVitalsSessionNow(sessionId, cancelSession = cancelVitalsSession) {
  if (!sessionId) return Promise.resolve();
  try {
    return Promise.resolve(cancelSession(sessionId)).catch(() => undefined);
  } catch {
    return Promise.resolve();
  }
}
