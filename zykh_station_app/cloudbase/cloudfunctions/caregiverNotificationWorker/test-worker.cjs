const assert = require("node:assert/strict");
const test = require("node:test");

const {
  createCaregiverNotificationWorker,
  FIXED_NOTIFICATION_CONTENT,
} = require("./worker");

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function createMemoryDatabase(seed = {}, behavior = {}) {
  const stores = new Map();
  let transactionTail = Promise.resolve();

  for (const [name, rows] of Object.entries(seed)) {
    stores.set(name, new Map(Object.entries(rows).map(([id, row]) => [id, clone(row)])));
  }

  function storeFor(name) {
    if (!stores.has(name)) stores.set(name, new Map());
    return stores.get(name);
  }

  function collection(name) {
    const store = storeFor(name);
    const query = (filter = {}, order = null, direction = "asc", maximum = 100) => ({
      where: next => query(next, order, direction, maximum),
      orderBy: (field, nextDirection) => query(filter, field, nextDirection, maximum),
      limit: nextMaximum => query(filter, order, direction, nextMaximum),
      get: async () => {
        let rows = Array.from(store.entries()).map(([id, row]) => ({ _id: id, ...clone(row) }));
        rows = rows.filter(row => Object.entries(filter).every(([key, value]) => row[key] === value));
        if (order) {
          rows.sort((left, right) => String(left[order] || "").localeCompare(String(right[order] || "")));
          if (direction === "desc") rows.reverse();
        }
        return { data: rows.slice(0, maximum) };
      },
    });
    return Object.assign(query(), {
      doc: id => ({
        get: async () => {
          if (behavior.failGet && behavior.failGet(name, id)) {
            return { errCode: -1, errMsg: "database get:fail simulated" };
          }
          if (!store.has(id)) {
            throw new Error(
              behavior.missingDocumentMessage || "document not found",
            );
          }
          return { data: { _id: id, ...clone(store.get(id)) } };
        },
        set: async ({ data }) => {
          if (behavior.failSet && behavior.failSet(name, id)) {
            return { errCode: -1, errMsg: "database set:fail simulated" };
          }
          store.set(id, clone(data));
          return { errCode: 0, errMsg: "database set:ok" };
        },
      }),
    });
  }

  const db = {
    collection,
    runTransaction(handler) {
      const result = transactionTail.then(() => handler({ collection }));
      transactionTail = result.then(() => undefined, () => undefined);
      return result;
    },
  };

  return {
    db,
    read(collectionName, id) {
      const row = storeFor(collectionName).get(id);
      return row ? clone(row) : null;
    },
  };
}

const COLLECTIONS = Object.freeze({
  notifications: "caregiver_notification_outbox",
  events: "medication_safety_events",
  memberships: "device_memberships",
  subscriptions: "caregiver_notification_subscriptions",
  receipts: "caregiver_event_receipts",
});

function validSeed() {
  return {
    caregiver_notification_outbox: {
      "notification-1": {
        notificationId: "notification-1",
        eventId: "event-1",
        deviceId: "device-1",
        membershipId: "membership-1",
        recipientOpenId: "openid-1",
        templateKey: "MEDICATION_SAFETY_ALERT",
        state: "PENDING",
        attempts: 0,
        createdAt: "2026-08-10T10:00:00.000Z",
        updatedAt: "2026-08-10T10:00:00.000Z",
      },
    },
    medication_safety_events: {
      "device-1-event-1": {
        eventId: "event-1",
        deviceId: "device-1",
        service_user_id: "wang-nainai",
        check_status: "PASSED",
        dispense_status: "DISPENSED",
        person_display_name: "王奶奶",
        medicine: { name: "布洛芬缓释胶囊" },
        reason_codes: ["PEPTIC_ULCER"],
      },
    },
    device_memberships: {
      "membership-1": {
        membershipId: "membership-1",
        openid: "openid-1",
        deviceId: "device-1",
        status: "ACTIVE",
        permissions: ["READ_SAFETY"],
        service_user_scopes: ["wang-nainai"],
      },
    },
    caregiver_notification_subscriptions: {
      "notification-subscription-0b151dcbfb7ec57e72044dae4fcb24d931ab66402ca448f44034c97cd85f9974": {
        openid: "openid-1",
        templateKey: "MEDICATION_SAFETY_ALERT",
        status: "AUTHORIZED",
        updatedAt: "2026-08-10T09:00:00.000Z",
      },
    },
    caregiver_event_receipts: {
      "device-1-event-1-openid-1": {
        eventId: "event-1",
        deviceId: "device-1",
        openid: "openid-1",
        state: "UNREAD",
        readAt: "",
        notificationState: "NOT_REQUESTED",
        notificationAttempts: 0,
        updatedAt: "2026-08-10T10:00:00.000Z",
      },
    },
    commands: {
      "command-1": { commandId: "command-1", action: "UNRELATED_EXISTING_COMMAND" },
    },
  };
}

test("a valid pending notification is claimed and sent with fixed minimal content", async () => {
  const memory = createMemoryDatabase(validSeed());
  const eventBefore = memory.read("medication_safety_events", "device-1-event-1");
  const receiptBefore = memory.read("caregiver_event_receipts", "device-1-event-1-openid-1");
  const commandBefore = memory.read("commands", "command-1");
  const requests = [];
  const worker = createCaregiverNotificationWorker({
    db: memory.db,
    collections: COLLECTIONS,
    now: () => new Date("2026-08-10T10:05:00.000Z"),
    createClaimToken: () => "claim-1",
    notificationPage: "pages/records/index",
    sender: {
      async send(request) {
        requests.push(clone(request));
        return { outcome: "SENT", code: "OK" };
      },
    },
  });

  const result = await worker.runOnce({ batchSize: 5 });

  assert.deepEqual(result, {
    ok: true,
    claimed: 1,
    sent: 1,
    failed: 0,
    resultUnknown: 0,
    staleConverged: 0,
  });
  assert.equal(requests.length, 1);
  assert.deepEqual(requests[0], {
    recipientOpenId: "openid-1",
    templateKey: "MEDICATION_SAFETY_ALERT",
    page: "pages/records/index",
    content: FIXED_NOTIFICATION_CONTENT,
  });
  const serializedRequest = JSON.stringify(requests[0]);
  for (const sensitiveText of ["王奶奶", "布洛芬缓释胶囊", "PEPTIC_ULCER"]) {
    assert.equal(serializedRequest.includes(sensitiveText), false);
  }
  assert.equal(memory.read("caregiver_notification_outbox", "notification-1").state, "SENT");
  assert.equal(memory.read("caregiver_notification_outbox", "notification-1").attempts, 1);
  assert.deepEqual(memory.read("medication_safety_events", "device-1-event-1"), eventBefore);
  const receiptAfter = memory.read("caregiver_event_receipts", "device-1-event-1-openid-1");
  assert.equal(receiptAfter.state, receiptBefore.state);
  assert.equal(receiptAfter.readAt, receiptBefore.readAt);
  assert.equal(receiptAfter.notificationState, "SENT");
  assert.equal(receiptAfter.notificationAttempts, 1);
  assert.deepEqual(memory.read("commands", "command-1"), commandBefore);
});

test("a claim write error never sends and leaves the notification pending", async () => {
  const memory = createMemoryDatabase(validSeed(), {
    failSet: (collectionName, id) => (
      collectionName === "caregiver_notification_outbox" && id === "notification-1"
    ),
  });
  let sendCalls = 0;
  const worker = createCaregiverNotificationWorker({
    db: memory.db,
    collections: COLLECTIONS,
    sender: { async send() { sendCalls += 1; return { outcome: "SENT", code: "OK" }; } },
  });

  await assert.rejects(worker.runOnce(), /NOTIFICATION_STORE_UNAVAILABLE/);

  assert.equal(sendCalls, 0);
  assert.equal(memory.read("caregiver_notification_outbox", "notification-1").state, "PENDING");
});

test("an operational document read error is retryable rather than a permanent rejection", async () => {
  const memory = createMemoryDatabase(validSeed(), {
    failGet: (collectionName, id) => (
      collectionName === "medication_safety_events" && id === "device-1-event-1"
    ),
  });
  let sendCalls = 0;
  const worker = createCaregiverNotificationWorker({
    db: memory.db,
    collections: COLLECTIONS,
    sender: { async send() { sendCalls += 1; return { outcome: "SENT", code: "OK" }; } },
  });

  await assert.rejects(worker.runOnce(), /NOTIFICATION_STORE_UNAVAILABLE/);

  assert.equal(sendCalls, 0);
  assert.equal(memory.read("caregiver_notification_outbox", "notification-1").state, "PENDING");
});

test("a missing event receipt fails closed before provider send", async () => {
  const seed = validSeed();
  seed.caregiver_event_receipts = {};
  const memory = createMemoryDatabase(seed, {
    missingDocumentMessage: "document.get:fail document with _id receipt-1 does not exist",
  });
  let sendCalls = 0;
  const worker = createCaregiverNotificationWorker({
    db: memory.db,
    collections: COLLECTIONS,
    sender: { async send() { sendCalls += 1; return { outcome: "SENT", code: "OK" }; } },
  });

  const result = await worker.runOnce();

  assert.equal(sendCalls, 0);
  assert.equal(result.failed, 1);
  const notification = memory.read("caregiver_notification_outbox", "notification-1");
  assert.equal(notification.state, "FAILED");
  assert.equal(notification.failureCode, "RECEIPT_NOT_AVAILABLE");
});

test("a mismatched event receipt fails closed before provider send", async () => {
  const seed = validSeed();
  seed.caregiver_event_receipts["device-1-event-1-openid-1"].openid = "another-openid";
  const memory = createMemoryDatabase(seed);
  let sendCalls = 0;
  const worker = createCaregiverNotificationWorker({
    db: memory.db,
    collections: COLLECTIONS,
    sender: { async send() { sendCalls += 1; return { outcome: "SENT", code: "OK" }; } },
  });

  const result = await worker.runOnce();

  assert.equal(sendCalls, 0);
  assert.equal(result.failed, 1);
  assert.equal(
    memory.read("caregiver_notification_outbox", "notification-1").failureCode,
    "RECEIPT_NOT_AVAILABLE",
  );
});

test("a revoked membership is failed during claim and never sent", async () => {
  const seed = validSeed();
  seed.device_memberships["membership-1"].status = "REVOKED";
  const memory = createMemoryDatabase(seed);
  let sendCalls = 0;
  const worker = createCaregiverNotificationWorker({
    db: memory.db,
    collections: COLLECTIONS,
    now: () => new Date("2026-08-10T10:05:00.000Z"),
    sender: { async send() { sendCalls += 1; } },
  });

  const result = await worker.runOnce({ batchSize: 5 });

  assert.equal(sendCalls, 0);
  assert.equal(result.failed, 1);
  assert.equal(result.claimed, 0);
  assert.equal(memory.read("caregiver_notification_outbox", "notification-1").state, "FAILED");
  assert.equal(
    memory.read("caregiver_notification_outbox", "notification-1").failureCode,
    "AUTHORIZATION_REVOKED",
  );
  const receipt = memory.read("caregiver_event_receipts", "device-1-event-1-openid-1");
  assert.equal(receipt.state, "UNREAD");
  assert.equal(receipt.readAt, "");
  assert.equal(receipt.notificationState, "FAILED");
  assert.equal(receipt.notificationAttempts, 0);
});

test("an explicit provider rejection becomes failed without retry", async () => {
  const memory = createMemoryDatabase(validSeed());
  const worker = createCaregiverNotificationWorker({
    db: memory.db,
    collections: COLLECTIONS,
    now: () => new Date("2026-08-10T10:05:00.000Z"),
    createClaimToken: () => "claim-rejected",
    sender: {
      async send() {
        return { outcome: "REJECTED", code: "USER_REFUSED" };
      },
    },
  });

  const result = await worker.runOnce();

  assert.equal(result.claimed, 1);
  assert.equal(result.failed, 1);
  assert.equal(result.resultUnknown, 0);
  const notification = memory.read("caregiver_notification_outbox", "notification-1");
  assert.equal(notification.state, "FAILED");
  assert.equal(notification.attempts, 1);
  assert.equal(notification.failureCode, "USER_REFUSED");
  assert.equal(
    memory.read("caregiver_event_receipts", "device-1-event-1-openid-1").notificationState,
    "FAILED",
  );
  assert.equal(
    memory.read("caregiver_event_receipts", "device-1-event-1-openid-1").notificationAttempts,
    1,
  );
});

test("a timeout becomes result unknown and is never automatically retried", async () => {
  const memory = createMemoryDatabase(validSeed());
  let sendCalls = 0;
  const worker = createCaregiverNotificationWorker({
    db: memory.db,
    collections: COLLECTIONS,
    now: () => new Date("2026-08-10T10:05:00.000Z"),
    createClaimToken: () => "claim-timeout",
    sender: {
      async send() {
        sendCalls += 1;
        throw new Error("ETIMEDOUT after request may have reached provider");
      },
    },
  });

  const first = await worker.runOnce();
  const second = await worker.runOnce();

  assert.equal(sendCalls, 1);
  assert.equal(first.claimed, 1);
  assert.equal(first.resultUnknown, 1);
  assert.equal(second.claimed, 0);
  const notification = memory.read("caregiver_notification_outbox", "notification-1");
  assert.equal(notification.state, "RESULT_UNKNOWN");
  assert.equal(notification.attempts, 1);
  assert.equal(notification.failureCode, "DELIVERY_RESULT_UNKNOWN");
  assert.equal(
    memory.read("caregiver_event_receipts", "device-1-event-1-openid-1").notificationState,
    "RESULT_UNKNOWN",
  );
  assert.equal(
    memory.read("caregiver_event_receipts", "device-1-event-1-openid-1").notificationAttempts,
    1,
  );
  assert.equal(
    Object.values(notification).some(value => String(value).includes("ETIMEDOUT")),
    false,
  );
});

test("a stale sending lease converges to result unknown without sending", async () => {
  const seed = validSeed();
  Object.assign(seed.caregiver_notification_outbox["notification-1"], {
    state: "SENDING",
    claimToken: "abandoned-claim",
    claimedAt: "2026-08-10T10:00:00.000Z",
    updatedAt: "2026-08-10T10:00:00.000Z",
    attempts: 1,
  });
  const memory = createMemoryDatabase(seed);
  let sendCalls = 0;
  const worker = createCaregiverNotificationWorker({
    db: memory.db,
    collections: COLLECTIONS,
    now: () => new Date("2026-08-10T10:10:00.000Z"),
    staleAfterMs: 5 * 60 * 1000,
    sender: { async send() { sendCalls += 1; } },
  });

  const result = await worker.runOnce();

  assert.equal(sendCalls, 0);
  assert.equal(result.staleConverged, 1);
  assert.equal(result.resultUnknown, 1);
  assert.equal(memory.read("caregiver_notification_outbox", "notification-1").state, "RESULT_UNKNOWN");
  assert.equal(memory.read("caregiver_notification_outbox", "notification-1").attempts, 1);
  assert.equal(
    memory.read("caregiver_event_receipts", "device-1-event-1-openid-1").notificationState,
    "RESULT_UNKNOWN",
  );
});

test("missing READ_SAFETY and an out-of-scope person both fail closed", async () => {
  for (const mutate of [
    membership => { membership.permissions = ["READ_PLAN"]; },
    membership => { membership.service_user_scopes = ["li-yeye"]; },
  ]) {
    const seed = validSeed();
    mutate(seed.device_memberships["membership-1"]);
    const memory = createMemoryDatabase(seed);
    let sendCalls = 0;
    const worker = createCaregiverNotificationWorker({
      db: memory.db,
      collections: COLLECTIONS,
      now: () => new Date("2026-08-10T10:05:00.000Z"),
      sender: { async send() { sendCalls += 1; } },
    });

    const result = await worker.runOnce();

    assert.equal(sendCalls, 0);
    assert.equal(result.failed, 1);
    assert.equal(memory.read("caregiver_notification_outbox", "notification-1").state, "FAILED");
    assert.equal(
      memory.read("caregiver_notification_outbox", "notification-1").failureCode,
      "AUTHORIZATION_REVOKED",
    );
  }
});

test("two workers racing the same pending row send at most once", async () => {
  const memory = createMemoryDatabase(validSeed());
  let sendCalls = 0;
  const sender = {
    async send() {
      sendCalls += 1;
      await new Promise(resolve => setImmediate(resolve));
      return { outcome: "SENT", code: "OK" };
    },
  };
  const common = {
    db: memory.db,
    collections: COLLECTIONS,
    now: () => new Date("2026-08-10T10:05:00.000Z"),
    sender,
  };
  const workerA = createCaregiverNotificationWorker({
    ...common,
    createClaimToken: () => "claim-racer-a",
  });
  const workerB = createCaregiverNotificationWorker({
    ...common,
    createClaimToken: () => "claim-racer-b",
  });

  const results = await Promise.all([workerA.runOnce(), workerB.runOnce()]);

  assert.equal(sendCalls, 1);
  assert.equal(results.reduce((sum, item) => sum + item.claimed, 0), 1);
  assert.equal(results.reduce((sum, item) => sum + item.sent, 0), 1);
  assert.equal(memory.read("caregiver_notification_outbox", "notification-1").state, "SENT");
});

test("a missing subscription authorization fails closed before provider send", async () => {
  const seed = validSeed();
  seed.caregiver_notification_subscriptions = {};
  const memory = createMemoryDatabase(seed);
  let sendCalls = 0;
  const worker = createCaregiverNotificationWorker({
    db: memory.db,
    collections: COLLECTIONS,
    now: () => new Date("2026-08-10T10:05:00.000Z"),
    sender: { async send() { sendCalls += 1; } },
  });

  const result = await worker.runOnce();

  assert.equal(sendCalls, 0);
  assert.equal(result.failed, 1);
  assert.equal(memory.read("caregiver_notification_outbox", "notification-1").state, "FAILED");
  assert.equal(
    memory.read("caregiver_notification_outbox", "notification-1").failureCode,
    "SUBSCRIPTION_NOT_AUTHORIZED",
  );
});

test("an already-read receipt suppresses a late notification without changing read audit", async () => {
  const seed = validSeed();
  Object.assign(seed.caregiver_event_receipts["device-1-event-1-openid-1"], {
    state: "READ",
    readAt: "2026-08-10T10:03:00.000Z",
  });
  const memory = createMemoryDatabase(seed);
  const receiptBefore = memory.read("caregiver_event_receipts", "device-1-event-1-openid-1");
  let sendCalls = 0;
  const worker = createCaregiverNotificationWorker({
    db: memory.db,
    collections: COLLECTIONS,
    now: () => new Date("2026-08-10T10:05:00.000Z"),
    sender: { async send() { sendCalls += 1; } },
  });

  const result = await worker.runOnce();

  assert.equal(sendCalls, 0);
  assert.equal(result.failed, 1);
  assert.equal(
    memory.read("caregiver_notification_outbox", "notification-1").failureCode,
    "ALREADY_READ",
  );
  const receiptAfter = memory.read("caregiver_event_receipts", "device-1-event-1-openid-1");
  assert.equal(receiptAfter.state, receiptBefore.state);
  assert.equal(receiptAfter.readAt, receiptBefore.readAt);
  assert.equal(receiptAfter.notificationState, "FAILED");
  assert.equal(receiptAfter.notificationAttempts, 0);
});
