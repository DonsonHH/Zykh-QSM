import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
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
  const sessionAdapter = await vite.ssrLoadModule("/src/adapters/vitalsSessionAdapter.js");
  assert.equal(
    typeof sessionAdapter.createVitalsPollPolicy,
    "function",
    "Vitals must expose its session polling policy through a runtime interface"
  );

  const policy = sessionAdapter.createVitalsPollPolicy("vitals-transport-recovery");
  const firstRetry = policy.observe({
    status: "failed",
    session_id: "vitals-transport-recovery",
    failure_reason: "transport_error"
  });
  assert.deepEqual(
    firstRetry,
    {
      kind: "retry",
      sessionId: "vitals-transport-recovery",
      delayMs: 700,
      consecutiveFailures: 1
    },
    "one transport error must retry the original session after a short delay"
  );
  assert.deepEqual(
    policy.observe({
      status: "failed",
      session_id: "vitals-transport-recovery",
      failure_reason: "transport_error"
    }),
    {
      kind: "retry",
      sessionId: "vitals-transport-recovery",
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
      sessionId: "vitals-transport-recovery",
      consecutiveFailures: 3
    },
    "only consecutive communication failures may stop the board measurement"
  );
  assert.deepEqual(
    policy.observe({
      status: "failed",
      session_id: "vitals-transport-recovery",
      failure_reason: "transport_error"
    }),
    {
      kind: "ignore",
      reason: "stop_already_requested"
    },
    "a stopped polling state must not emit a second board cancellation"
  );
  assert.deepEqual(
    policy.requestCancel("vitals-transport-recovery"),
    {
      kind: "ignore",
      reason: "stop_already_requested"
    },
    "cleanup after the third communication failure must not cancel the same session again"
  );

  const recoveryPolicy = sessionAdapter.createVitalsPollPolicy("vitals-transport-recovery");
  recoveryPolicy.observe({
    status: "failed",
    session_id: "vitals-transport-recovery",
    failure_reason: "transport_error"
  });
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
    recoveryPolicy.observe({
      status: "failed",
      session_id: "vitals-transport-recovery",
      failure_reason: "transport_error"
    }),
    {
      kind: "retry",
      sessionId: "vitals-transport-recovery",
      delayMs: 700,
      consecutiveFailures: 1
    },
    "a recovered connection must reset the consecutive failure count"
  );

  const measurementFailurePolicy = sessionAdapter.createVitalsPollPolicy("vitals-no-finger");
  assert.deepEqual(
    measurementFailurePolicy.observe({
      status: "failed",
      session_id: "vitals-no-finger",
      failure_reason: "no_finger"
    }),
    { kind: "accept" },
    "a real measurement failure must be shown immediately instead of entering communication retry"
  );

  const replacementPolicy = sessionAdapter.createVitalsPollPolicy("vitals-new-session");
  assert.deepEqual(
    replacementPolicy.observe({
      status: "complete",
      session_id: "vitals-old-session",
      failure_reason: null,
      heart_rate: 72,
      spo2: 98,
      temperature: 36.5
    }),
    {
      kind: "ignore",
      reason: "stale_session"
    },
    "a late response from the replaced session must not overwrite the new measurement"
  );

  for (const trigger of ["user cancellation", "page unmount"]) {
    const cleanupPolicy = sessionAdapter.createVitalsPollPolicy(
      `vitals-${trigger.replace(" ", "-")}`
    );
    assert.deepEqual(
      cleanupPolicy.requestCancel(`vitals-${trigger.replace(" ", "-")}`),
      {
        kind: "stop",
        sessionId: `vitals-${trigger.replace(" ", "-")}`
      },
      `${trigger} must request immediate board cleanup`
    );
  }

  assert.equal(
    typeof sessionAdapter.cancelVitalsSessionNow,
    "function",
    "Vitals must expose its immediate session cleanup boundary"
  );

  const oneShotPolicy = sessionAdapter.createVitalsPollPolicy("vitals-one-shot-stop");
  const boardCancellations = [];
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    const action = oneShotPolicy.observe({
      status: "failed",
      session_id: "vitals-one-shot-stop",
      failure_reason: "transport_error"
    });
    if (action.kind === "stop") {
      await sessionAdapter.cancelVitalsSessionNow(action.sessionId, async (sessionId) => {
        boardCancellations.push(sessionId);
      });
    }
  }
  const cleanupAfterStop = oneShotPolicy.requestCancel("vitals-one-shot-stop");
  if (cleanupAfterStop.kind === "stop") {
    await sessionAdapter.cancelVitalsSessionNow(cleanupAfterStop.sessionId, async (sessionId) => {
      boardCancellations.push(sessionId);
    });
  }
  assert.deepEqual(
    boardCancellations,
    ["vitals-one-shot-stop"],
    "the third consecutive transport failure must emit exactly one board cancellation"
  );

  for (const trigger of ["user cancellation", "page unmount"]) {
    let cancelledSessionId = "";
    let releaseCancellation;
    const pendingCancellation = new Promise((resolve) => {
      releaseCancellation = resolve;
    });
    const cancellation = sessionAdapter.cancelVitalsSessionNow(
      `vitals-${trigger.replace(" ", "-")}`,
      (sessionId) => {
        cancelledSessionId = sessionId;
        return pendingCancellation;
      }
    );
    assert.equal(
      cancelledSessionId,
      `vitals-${trigger.replace(" ", "-")}`,
      `${trigger} must issue board cleanup immediately without awaiting the response`
    );
    releaseCancellation({ ok: true });
    await cancellation;
  }

  const vitalsSource = await readFile(`${root}src/pages/Vitals.jsx`, "utf8");
  const sessionSource = await readFile(`${root}src/modules/vitalsSession.js`, "utf8");
  assert.ok(
    sessionSource.includes("requestBoardCancellation(activeSession);"),
    "session module unmount must use the tested immediate cleanup boundary"
  );
  assert.ok(
    sessionSource.includes("await requestBoardCancellation(currentSession);"),
    "explicit user cancellation must use the tested immediate cleanup boundary"
  );
  assert.ok(
    sessionSource.includes('if (pollAction.kind === "ignore") return;'),
    "ignored stale responses must not reach the component state setters"
  );
  assert.ok(
    sessionSource.includes("createVitalsPollPolicy(data.session_id)"),
    "the polling policy must bind itself to the newly started session"
  );
  assert.ok(
    sessionSource.includes("sessionIdRef.current = data.session_id;"),
    "a newly started session must be available to unmount cleanup before the next effect"
  );
  assert.ok(
    sessionSource.includes('phaseRef.current = data.status || "failed";'),
    "unmount cleanup must synchronously know whether the current session is still active"
  );
  assert.ok(vitalsSource.includes("useVitalsSession("), "page must consume the deep session module");
  assert.doesNotMatch(
    vitalsSource,
    /loadVitalsSession|prepareQsmVitals|startVitalsSession|sessionIdRef|pollPolicyRef/,
    "presentation page must not own gateway calls or session lifecycle refs"
  );
} finally {
  await vite.close();
}

console.log("vitals transport recovery: ok");
