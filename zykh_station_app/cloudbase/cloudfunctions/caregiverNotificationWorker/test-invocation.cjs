const assert = require("node:assert/strict");
const test = require("node:test");

const { createInvocationHandler } = require("./invocation");

test("a miniprogram OPENID is rejected even when the payload spoofs the timer", async () => {
  let workerCalls = 0;
  const handler = createInvocationHandler({
    worker: { async runOnce() { workerCalls += 1; return { ok: true }; } },
    getOpenId: () => "attacker-openid",
    controlToken: "service-control-token",
    timerTriggerName: "caregiver-notification-worker-timer",
  });

  const result = await handler({
    Type: "Timer",
    TriggerName: "caregiver-notification-worker-timer",
    controlToken: "service-control-token",
  });

  assert.deepEqual(result, { ok: false, error: "WORKER_INVOCATION_FORBIDDEN" });
  assert.equal(workerCalls, 0);
});

test("the configured timer trigger can run one bounded worker batch", async () => {
  const calls = [];
  const handler = createInvocationHandler({
    worker: {
      async runOnce(options) {
        calls.push(options);
        return { ok: true, claimed: 2, sent: 2 };
      },
    },
    getOpenId: () => "",
    controlToken: "service-control-token",
    timerTriggerName: "caregiver-notification-worker-timer",
  });

  const result = await handler({
    Type: "Timer",
    TriggerName: "caregiver-notification-worker-timer",
    batchSize: 7,
  });

  assert.deepEqual(result, { ok: true, claimed: 2, sent: 2 });
  assert.deepEqual(calls, [{ batchSize: 7 }]);
});

test("a controlled service call with the configured token can run the worker", async () => {
  const calls = [];
  const handler = createInvocationHandler({
    worker: {
      async runOnce(options) {
        calls.push(options);
        return { ok: true, claimed: 0 };
      },
    },
    getOpenId: () => "",
    controlToken: "service-control-token",
    timerTriggerName: "caregiver-notification-worker-timer",
  });

  const result = await handler({
    controlToken: "service-control-token",
    batchSize: 3,
  });

  assert.deepEqual(result, { ok: true, claimed: 0 });
  assert.deepEqual(calls, [{ batchSize: 3 }]);
});

test("an HTTP-shaped direct call is rejected even with the control token", async () => {
  let workerCalls = 0;
  const handler = createInvocationHandler({
    worker: { async runOnce() { workerCalls += 1; } },
    getOpenId: () => "",
    controlToken: "service-control-token",
    timerTriggerName: "caregiver-notification-worker-timer",
  });

  const result = await handler({
    httpMethod: "POST",
    body: JSON.stringify({ controlToken: "service-control-token" }),
    controlToken: "service-control-token",
  });

  assert.deepEqual(result, { ok: false, error: "WORKER_INVOCATION_FORBIDDEN" });
  assert.equal(workerCalls, 0);
});

test("a deployment probe reports capability without reading or sending notifications", async () => {
  let workerCalls = 0;
  const invoke = createInvocationHandler({
    worker: { async runOnce() { workerCalls += 1; } },
    getOpenId: () => "",
    timerTriggerName: "caregiver-notification-worker-timer",
  });

  const result = await invoke({ action: "PING" });

  assert.deepEqual(result, {
    ok: true,
    capability: "caregiverNotificationWorker",
    version: "v1",
  });
  assert.equal(workerCalls, 0);
});
