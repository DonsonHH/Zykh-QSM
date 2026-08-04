import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const root = fileURLToPath(new URL("../", import.meta.url));
const vite = await createServer({
  root,
  logLevel: "silent",
  server: { middlewareMode: true },
  appType: "custom"
});

try {
  const module = await vite.ssrLoadModule("/src/pages/Vitals.jsx");
  assert.equal(
    typeof module.createVitalsPollPolicy,
    "function",
    "Vitals must expose its session polling policy through a runtime interface"
  );

  const policy = module.createVitalsPollPolicy();
  assert.deepEqual(
    policy.observe({
      status: "failed",
      session_id: "vitals-transport-recovery",
      failure_reason: "transport_error"
    }),
    {
      kind: "retry",
      delayMs: 700,
      consecutiveFailures: 1
    },
    "one transport error must keep the current session alive for a short retry"
  );
  assert.deepEqual(
    policy.observe({
      status: "failed",
      session_id: "vitals-transport-recovery",
      failure_reason: "transport_error"
    }),
    {
      kind: "retry",
      delayMs: 700,
      consecutiveFailures: 2
    },
    "a second consecutive transport error must still retain the session"
  );
  assert.deepEqual(
    policy.observe({
      status: "failed",
      session_id: "vitals-transport-recovery",
      failure_reason: "transport_error"
    }),
    {
      kind: "stop",
      consecutiveFailures: 3
    },
    "only consecutive communication failures may stop the board measurement"
  );

  const recoveryPolicy = module.createVitalsPollPolicy();
  recoveryPolicy.observe({ status: "failed", failure_reason: "transport_error" });
  assert.deepEqual(
    recoveryPolicy.observe({
      status: "stabilizing",
      session_id: "vitals-transport-recovery",
      hardware_started: true,
      failure_reason: null
    }),
    { kind: "accept" },
    "a recovered status response must resume the existing session"
  );
  assert.deepEqual(
    recoveryPolicy.observe({ status: "failed", failure_reason: "transport_error" }),
    {
      kind: "retry",
      delayMs: 700,
      consecutiveFailures: 1
    },
    "a recovered connection must reset the consecutive failure count"
  );
} finally {
  await vite.close();
}

console.log("vitals transport recovery: ok");
