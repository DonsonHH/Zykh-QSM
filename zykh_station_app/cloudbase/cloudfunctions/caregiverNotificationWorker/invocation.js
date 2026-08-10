const crypto = require("node:crypto");

function text(value) {
  return String(value || "").trim();
}

function isHttpStyle(event) {
  return Boolean(
    event
    && (
      event.httpMethod
      || event.headers
      || event.requestContext
      || event.queryStringParameters
      || event.isBase64Encoded
      || Object.prototype.hasOwnProperty.call(event, "body")
    )
  );
}

function tokensMatch(provided, expected) {
  const providedBuffer = Buffer.from(text(provided), "utf8");
  const expectedBuffer = Buffer.from(text(expected), "utf8");
  return expectedBuffer.length > 0
    && providedBuffer.length === expectedBuffer.length
    && crypto.timingSafeEqual(providedBuffer, expectedBuffer);
}

function createInvocationHandler({
  worker,
  getOpenId,
  timerTriggerName = "",
  controlToken = "",
}) {
  if (!worker || typeof worker.runOnce !== "function") throw new Error("notification worker required");
  if (typeof getOpenId !== "function") throw new Error("identity adapter required");

  return async function invoke(event = {}) {
    if (text(getOpenId(event))) {
      return { ok: false, error: "WORKER_INVOCATION_FORBIDDEN" };
    }
    if (isHttpStyle(event)) return { ok: false, error: "WORKER_INVOCATION_FORBIDDEN" };
    if (text(event.action).toUpperCase() === "PING") {
      return {
        ok: true,
        capability: "caregiverNotificationWorker",
        version: "v1",
      };
    }
    const timerAllowed = (
      text(event.Type || event.type).toUpperCase() === "TIMER"
      && text(event.TriggerName || event.triggerName) === text(timerTriggerName)
      && Boolean(text(timerTriggerName))
    );
    if (timerAllowed) return worker.runOnce({ batchSize: event.batchSize });
    if (tokensMatch(event.controlToken, controlToken)) {
      return worker.runOnce({ batchSize: event.batchSize });
    }
    return { ok: false, error: "WORKER_INVOCATION_FORBIDDEN" };
  };
}

module.exports = { createInvocationHandler };
