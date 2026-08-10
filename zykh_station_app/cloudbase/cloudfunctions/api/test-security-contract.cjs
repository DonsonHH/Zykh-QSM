const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");

let inserted = 0;
const insertedRows = [];
const stores = new Map();
let currentOpenId = "wechat-openid";
let transactionTail = Promise.resolve();
let failPairingCodeSet = false;
let failMembershipQuery = false;
let failMembershipSet = false;
let failSafetyEventGet = false;
let failSafetyEventSet = false;
let failSafetyReceiptSet = false;
let failSafetyNotificationSet = false;
function storeFor(name) {
  if (!stores.has(name)) stores.set(name, new Map());
  return stores.get(name);
}
function collection(name) {
  const store = storeFor(name);
  const makeQuery = (filter = {}, order = null, direction = "asc", offset = 0, maximum = 100) => ({
    where: next => makeQuery(next, order, direction, offset, maximum),
    orderBy: (field, nextDirection) => makeQuery(filter, field, nextDirection, offset, maximum),
    skip: nextOffset => makeQuery(filter, order, direction, nextOffset, maximum),
    limit: nextMaximum => makeQuery(filter, order, direction, offset, nextMaximum),
    get: async () => {
      if (name === "device_memberships" && failMembershipQuery) {
        return { errCode: -1, errMsg: "database query:fail injected" };
      }
      let rows = Array.from(store.entries()).map(([id, row]) => Object.assign({ _id: id }, row));
      rows = rows.filter(row => Object.entries(filter).every(([key, value]) => row[key] === value));
      if (order) {
        rows.sort((left, right) => String(left[order] || "").localeCompare(String(right[order] || "")));
        if (direction === "desc") rows.reverse();
      }
      return { data: rows.slice(offset, offset + maximum) };
    },
  });
  return Object.assign(makeQuery(), {
    add: async ({ data }) => {
      const id = `${name}-${store.size + 1}`;
      store.set(id, data);
      if (name === "commands") {
        inserted += 1;
        insertedRows.push(data);
      }
      return { _id: id, data };
    },
    doc: id => ({
      get: async () => {
        if (name === "medication_safety_events" && failSafetyEventGet) {
          return { errCode: -1, errMsg: "document.get:fail transient database error" };
        }
        if (!store.has(id)) throw new Error("missing document");
        return { data: Object.assign({ _id: id }, store.get(id)) };
      },
      set: async ({ data }) => {
        if (name === "device_pairing_codes" && failPairingCodeSet) {
          return { errCode: -1, errMsg: "document.set:fail injected" };
        }
        if (name === "device_memberships" && failMembershipSet) {
          return { errCode: -1, errMsg: "document.set:fail injected" };
        }
        if (name === "medication_safety_events" && failSafetyEventSet) {
          return { errCode: -1, errMsg: "document.set:fail injected" };
        }
        if (name === "caregiver_event_receipts" && failSafetyReceiptSet) {
          return { errCode: -1, errMsg: "document.set:fail injected" };
        }
        if (name === "caregiver_notification_outbox" && failSafetyNotificationSet) {
          return { errCode: -1, errMsg: "document.set:fail injected" };
        }
        store.set(id, data);
        return { errCode: 0, errMsg: "document.set:ok" };
      },
      remove: async () => { store.delete(id); },
    }),
  });
}

function transactionCollection(name) {
  const direct = collection(name);
  return Object.assign({}, direct, {
    where: () => {
      throw new Error("TRANSACTION_QUERY_FORBIDDEN");
    },
  });
}
const fakeCloud = {
  DYNAMIC_CURRENT_ENV: "test",
  init: () => {},
  getWXContext: () => ({ OPENID: currentOpenId }),
  database: () => ({
    collection,
    runTransaction: handler => {
      const result = transactionTail.then(async () => {
        const snapshot = new Map(
          Array.from(stores.entries()).map(([name, store]) => [
            name,
            new Map(
              Array.from(store.entries()).map(([id, row]) => [
                id,
                JSON.parse(JSON.stringify(row)),
              ]),
            ),
          ]),
        );
        try {
          return await handler({ collection: transactionCollection });
        } catch (error) {
          stores.clear();
          for (const [name, store] of snapshot.entries()) stores.set(name, store);
          throw error;
        }
      });
      transactionTail = result.then(() => undefined, () => undefined);
      return result;
    },
  }),
};

const originalLoad = Module._load;
Module._load = function load(request, parent, isMain) {
  if (request === "wx-server-sdk") return fakeCloud;
  return originalLoad.call(this, request, parent, isMain);
};

const cloudFunction = require(path.resolve(__dirname, "index.js"));
const { createMembershipModule } = require(path.resolve(__dirname, "memberships.js"));
const { canonicalPayloadDigest } = require(path.resolve(__dirname, "medicationSafetyEvents.js"));

async function invokeHttp(action, data) {
  const response = await cloudFunction.main({
    httpMethod: "POST",
    body: JSON.stringify({ action, data }),
  });
  return JSON.parse(response.body);
}

async function run() {
  const source = fs.readFileSync(path.resolve(__dirname, "index.js"), "utf8");
  const deploySource = fs.readFileSync(
    path.resolve(__dirname, "../../../scripts/deploy_cloudbase_sync.py"),
    "utf8",
  );
  assert.match(
    source,
    /2\.6-station-pairing-notification-worker/,
    "station pairing issue schema revision was not advanced",
  );
  for (const collectionName of [
    "medication_safety_events",
    "caregiver_event_receipts",
    "caregiver_notification_outbox",
    "caregiver_notification_subscriptions",
    "device_memberships",
    "device_pairing_codes",
  ]) {
    assert.match(deploySource, new RegExp(`\\b${collectionName}\\b`), `${collectionName} is missing from deploy setup`);
  }
  for (const moduleName of [
    "medicationSafetyEvents.js",
    "memberships.js",
    "caregiverNotificationWorker",
    "subscribeMessageSender.js",
    "invocation.js",
    "worker.js",
  ]) {
    assert.match(deploySource, new RegExp(moduleName.replace(".", "\\.")), `${moduleName} is missing from the function archive`);
  }
  assert.match(
    deploySource,
    /2\.6-station-pairing-notification-worker/,
    "deployment verification must not accept an older parallel schemaVersion=2 contract",
  );
  assert.doesNotMatch(
    deploySource,
    /TARGET_SCHEMA_REVISION\s*=\s*"2\.5-caregiver-safety-events"/,
    "deployment verification still targets the obsolete 2.5 revision",
  );
  assert.match(
    deploySource,
    /capabilities\.get\("devicePairing"\)\s*==\s*"v1"/,
    "deployment verification must wait for the secure pairing capability",
  );
  assert.match(
    deploySource,
    /capabilities\.get\("caregiverNotificationOutbox"\)\s*==\s*"v1"/,
    "deployment verification must wait for the notification outbox capability",
  );
  assert.match(
    deploySource,
    /capabilities\.get\("devicePairingIssue"\)\s*==\s*"v1"/,
    "deployment verification must wait for the Station pairing issuer capability",
  );
  assert.match(
    deploySource,
    /capabilities\.get\("caregiverNotificationWorker"\)\s*==\s*"v1"/,
    "deployment verification must wait for the notification worker capability",
  );
  assert.match(deploySource, /caregiver-notification-worker-timer/);
  assert.match(deploySource, /desired\s*=\s*"OPEN"\s*if\s*enable\s*else\s*"CLOSE"/);
  assert.match(
    source,
    /normalized\.createdAt = firstPresent\(\s*row\.measured_at/,
    "vitals history is sorted by synchronization time instead of measurement time",
  );
  const ping = await cloudFunction.main({ action: "PING", data: {} });
  assert.equal(ping.schemaRevision, "2.6-station-pairing-notification-worker");
  assert.equal(ping.capabilities && ping.capabilities.medicationSafetyEvents, "v1");
  assert.equal(ping.capabilities && ping.capabilities.caregiverMembership, "v1");
  assert.equal(ping.capabilities && ping.capabilities.inquiryDetail, "v1");
  assert.equal(ping.capabilities && ping.capabilities.snapshotBatch, "v2");
  assert.equal(ping.capabilities && ping.capabilities.devicePairing, "v1");
  assert.equal(ping.capabilities && ping.capabilities.devicePairingIssue, "v1");
  assert.equal(ping.capabilities && ping.capabilities.caregiverNotificationOutbox, "v1");
  assert.equal(ping.capabilities && ping.capabilities.caregiverNotificationWorker, "v1");
  assert.equal(ping.collections && ping.collections.devicePairingCodes, "device_pairing_codes");
  assert.equal(
    ping.collections && ping.collections.caregiverNotificationOutbox,
    "caregiver_notification_outbox",
  );
  assert.equal(
    ping.collections && ping.collections.caregiverNotificationSubscriptions,
    "caregiver_notification_subscriptions",
  );

  storeFor("service_users").set("clock-device-user-clock-wang", {
    id: "clock-wang",
    deviceId: "clock-device",
    archived: false,
  });
  const deterministicMemberships = createMembershipModule({
    db: fakeCloud.database(),
    collections: {
      devicePairingCodes: "device_pairing_codes",
      serviceUsers: "service_users",
    },
    nowText: () => "2026-08-10 12:00:00",
    nowEpochMs: () => Date.parse("2026-08-10T04:00:00.000Z"),
  });
  const deterministicIssue = await deterministicMemberships.issuePairingCode({
    deviceId: "clock-device",
    codeHash: "7".repeat(64),
    serviceUserScopes: ["clock-wang"],
    ttlSeconds: 600,
  });
  assert.equal(deterministicIssue.expiresAt, "2026-08-10T04:10:00.000Z");
  assert.equal(
    storeFor("device_pairing_codes").get(`pairing-${"7".repeat(64)}`).createdAt,
    "2026-08-10 12:00:00",
  );
  storeFor("service_users").delete("clock-device-user-clock-wang");
  storeFor("device_pairing_codes").delete(`pairing-${"7".repeat(64)}`);

  const issuePairingOriginalSharedSecret = process.env.DEVICE_SECRET;
  const issuePairingOriginalDeviceSecrets = process.env.DEVICE_SECRETS;
  process.env.DEVICE_SECRET = "server-test-secret";
  delete process.env.DEVICE_SECRETS;
  storeFor("service_users").set("zykh-qsm-001-user-wang-nainai", {
    id: "wang-nainai",
    name: "王奶奶",
    deviceId: "zykh-qsm-001",
    archived: false,
  });
  storeFor("service_users").set("zykh-qsm-001-user-archived", {
    id: "archived-person",
    name: "已归档对象",
    deviceId: "zykh-qsm-001",
    archived: true,
  });
  const issueWithoutSecret = await invokeHttp("ISSUE_DEVICE_PAIRING_CODE", {
    deviceId: "zykh-qsm-001",
    codeHash: "b".repeat(64),
    serviceUserScopes: ["wang-nainai"],
    ttlSeconds: 600,
  });
  assert.equal(issueWithoutSecret.ok, false);
  assert.match(issueWithoutSecret.error, /per-device|unauthorized/);
  const issueWithSharedSecretOnly = await invokeHttp("ISSUE_DEVICE_PAIRING_CODE", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    codeHash: "1".repeat(64),
    serviceUserScopes: ["wang-nainai"],
    ttlSeconds: 600,
  });
  assert.equal(issueWithSharedSecretOnly.ok, false);
  assert.match(issueWithSharedSecretOnly.error, /per-device|unauthorized/);
  process.env.DEVICE_SECRETS = JSON.stringify({
    "zykh-qsm-001": "server-test-secret",
  });
  const issueWithCallerSelectedAuthority = await invokeHttp("ISSUE_DEVICE_PAIRING_CODE", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    codeHash: "c".repeat(64),
    serviceUserScopes: ["wang-nainai"],
    ttlSeconds: 600,
    role: "OWNER",
    permissions: ["CREATE_COMMAND"],
  });
  assert.equal(issueWithCallerSelectedAuthority.ok, false);
  assert.match(issueWithCallerSelectedAuthority.error, /PAIRING_CODE_ISSUE_INVALID/);
  const issueWithoutScope = await invokeHttp("ISSUE_DEVICE_PAIRING_CODE", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    codeHash: "d".repeat(64),
    serviceUserScopes: [],
    ttlSeconds: 600,
  });
  assert.equal(issueWithoutScope.ok, false);
  assert.match(issueWithoutScope.error, /PAIRING_CODE_ISSUE_INVALID/);
  const issueWithForgedScope = await invokeHttp("ISSUE_DEVICE_PAIRING_CODE", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    codeHash: "9".repeat(64),
    serviceUserScopes: ["not-a-current-service-user"],
    ttlSeconds: 600,
  });
  assert.equal(issueWithForgedScope.ok, false);
  assert.match(issueWithForgedScope.error, /PAIRING_CODE_ISSUE_INVALID/);
  const issueWithArchivedScope = await invokeHttp("ISSUE_DEVICE_PAIRING_CODE", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    codeHash: "8".repeat(64),
    serviceUserScopes: ["archived-person"],
    ttlSeconds: 600,
  });
  assert.equal(issueWithArchivedScope.ok, false);
  assert.match(issueWithArchivedScope.error, /PAIRING_CODE_ISSUE_INVALID/);
  failPairingCodeSet = true;
  const issueWithDatabaseWriteFailure = await invokeHttp("ISSUE_DEVICE_PAIRING_CODE", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    codeHash: "2".repeat(64),
    serviceUserScopes: ["wang-nainai"],
    ttlSeconds: 600,
  });
  failPairingCodeSet = false;
  assert.equal(issueWithDatabaseWriteFailure.ok, false);
  assert.match(issueWithDatabaseWriteFailure.error, /PAIRING_CODE_ISSUE_INVALID/);
  assert.equal(storeFor("device_pairing_codes").has(`pairing-${"2".repeat(64)}`), false);
  for (const ttlSeconds of [299, 901]) {
    const invalidTtl = await invokeHttp("ISSUE_DEVICE_PAIRING_CODE", {
      deviceId: "zykh-qsm-001",
      deviceSecret: "server-test-secret",
      codeHash: "e".repeat(64),
      serviceUserScopes: ["wang-nainai"],
      ttlSeconds,
    });
    assert.equal(invalidTtl.ok, false);
    assert.match(invalidTtl.error, /PAIRING_CODE_ISSUE_INVALID/);
  }
  const concurrentIssueHash = "f".repeat(64);
  const concurrentIssues = await Promise.all([
    invokeHttp("ISSUE_DEVICE_PAIRING_CODE", {
      deviceId: "zykh-qsm-001",
      deviceSecret: "server-test-secret",
      codeHash: concurrentIssueHash,
      serviceUserScopes: ["wang-nainai"],
      ttlSeconds: 600,
    }),
    invokeHttp("ISSUE_DEVICE_PAIRING_CODE", {
      deviceId: "zykh-qsm-001",
      deviceSecret: "server-test-secret",
      codeHash: concurrentIssueHash,
      serviceUserScopes: ["wang-nainai"],
      ttlSeconds: 600,
    }),
  ]);
  assert.equal(concurrentIssues.filter(result => result.ok === true).length, 1);
  assert.equal(
    concurrentIssues.filter(result => /PAIRING_CODE_ISSUE_INVALID/.test(result.error || "")).length,
    1,
  );
  const issuedPairingHash = "3dd27a27fd12479222e4d95bdc2161012a5695b7426971de78e713b28002c403";
  const issueStartedAt = Date.now();
  const issuedPairing = await invokeHttp("ISSUE_DEVICE_PAIRING_CODE", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    codeHash: issuedPairingHash,
    serviceUserScopes: ["wang-nainai"],
    ttlSeconds: 600,
  });
  assert.equal(issuedPairing.ok, true);
  assert.equal(issuedPairing.deviceId, "zykh-qsm-001");
  assert.equal(issuedPairing.role, "CAREGIVER");
  assert.deepEqual(issuedPairing.permissions, [
    "READ_SAFETY",
    "READ_INQUIRY",
    "READ_PLAN",
    "READ_PROFILE",
    "READ_RECORD",
    "READ_VITALS",
    "READ_MEDICINE",
  ]);
  assert.deepEqual(issuedPairing.serviceUserScopes, ["wang-nainai"]);
  assert.match(issuedPairing.expiresAt, /^\d{4}-\d{2}-\d{2}T/);
  const issuedTtlMs = Date.parse(issuedPairing.expiresAt) - issueStartedAt;
  assert.ok(issuedTtlMs >= 599_000 && issuedTtlMs <= 601_000);
  const storedIssuedPairing = storeFor("device_pairing_codes")
    .get(`pairing-${issuedPairingHash}`);
  assert.equal(storedIssuedPairing.codeHash, issuedPairingHash);
  assert.equal(storedIssuedPairing.deviceId, "zykh-qsm-001");
  assert.equal(storedIssuedPairing.status, "UNUSED");
  assert.equal(Object.prototype.hasOwnProperty.call(storedIssuedPairing, "pairingCode"), false);
  assert.equal(Object.prototype.hasOwnProperty.call(storedIssuedPairing, "code"), false);
  assert.equal(Object.prototype.hasOwnProperty.call(storedIssuedPairing, "deviceSecret"), false);
  storedIssuedPairing.status = "CONSUMED";
  storeFor("device_pairing_codes").set(`pairing-${issuedPairingHash}`, storedIssuedPairing);
  const repeatedIssue = await invokeHttp("ISSUE_DEVICE_PAIRING_CODE", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    codeHash: issuedPairingHash,
    serviceUserScopes: ["wang-nainai"],
    ttlSeconds: 600,
  });
  assert.equal(repeatedIssue.ok, false);
  assert.match(repeatedIssue.error, /PAIRING_CODE_ISSUE_INVALID/);
  assert.equal(
    storeFor("device_pairing_codes").get(`pairing-${issuedPairingHash}`).status,
    "CONSUMED",
  );
  if (issuePairingOriginalSharedSecret === undefined) delete process.env.DEVICE_SECRET;
  else process.env.DEVICE_SECRET = issuePairingOriginalSharedSecret;
  if (issuePairingOriginalDeviceSecrets === undefined) delete process.env.DEVICE_SECRETS;
  else process.env.DEVICE_SECRETS = issuePairingOriginalDeviceSecrets;
  storeFor("service_users").delete("zykh-qsm-001-user-wang-nainai");
  storeFor("service_users").delete("zykh-qsm-001-user-archived");

  storeFor("device_memberships").set("membership-bind-active", {
    openid: "binding-openid",
    deviceId: "binding-device-visible",
    role: "CAREGIVER",
    service_user_scopes: ["wang-nainai"],
    permissions: ["READ_SAFETY", "READ_PLAN"],
    status: "ACTIVE",
    updatedAt: "2026-08-10 10:00:00",
  });
  storeFor("device_memberships").set("membership-bind-revoked", {
    openid: "binding-openid",
    deviceId: "binding-device-revoked",
    role: "CAREGIVER",
    permissions: ["READ_SAFETY"],
    status: "REVOKED",
  });
  storeFor("device_memberships").set("membership-bind-other-openid", {
    openid: "another-binding-openid",
    deviceId: "binding-device-other",
    role: "OWNER",
    permissions: ["READ_SAFETY"],
    status: "ACTIVE",
  });
  storeFor("devices").set("binding-device-visible", {
    deviceId: "binding-device-visible",
    name: "王奶奶家的药箱",
    online: true,
    lastSeenAt: "2026-08-10 09:59:59",
    deviceSecret: "must-never-leak",
    syncSummary: { serviceUsers: [{ id: "wang-nainai", name: "王奶奶" }] },
  });
  currentOpenId = "binding-openid";
  const myDevices = await cloudFunction.main({ action: "GET_MY_DEVICES", data: {} });
  assert.deepEqual(myDevices, {
    ok: true,
    items: [{
      deviceId: "binding-device-visible",
      name: "王奶奶家的药箱",
      online: true,
      lastSeenAt: "2026-08-10 09:59:59",
      role: "CAREGIVER",
      permissions: ["READ_SAFETY", "READ_PLAN"],
      serviceUserScopes: ["wang-nainai"],
    }],
  });
  const myDevicesOverHttp = await invokeHttp("GET_MY_DEVICES", {});
  assert.equal(myDevicesOverHttp.ok, false);
  assert.match(myDevicesOverHttp.error, /miniprogram function invocation required/);

  const queryFailureCode = "ZYKH-QSM-PAIR-QUERY-FAILURE";
  const queryFailureHash = crypto.createHash("sha256").update(queryFailureCode).digest("hex");
  storeFor("device_pairing_codes").set(`pairing-${queryFailureHash}`, {
    codeHash: queryFailureHash,
    deviceId: "binding-device-query-failure",
    role: "CAREGIVER",
    service_user_scopes: ["li-yeye"],
    permissions: ["READ_SAFETY"],
    status: "UNUSED",
    expiresAt: "2099-12-31T23:59:59+08:00",
  });
  currentOpenId = "query-failure-openid";
  failMembershipQuery = true;
  const queryFailureResult = await cloudFunction.main({
    action: "REDEEM_DEVICE_PAIRING_CODE",
    data: { pairingCode: queryFailureCode },
  });
  failMembershipQuery = false;
  assert.equal(queryFailureResult.ok, false);
  assert.equal(
    storeFor("device_pairing_codes").get(`pairing-${queryFailureHash}`).status,
    "UNUSED",
  );
  assert.equal(
    Array.from(storeFor("device_memberships").values())
      .some(row => row.deviceId === "binding-device-query-failure"),
    false,
  );
  storeFor("device_pairing_codes").delete(`pairing-${queryFailureHash}`);

  const membershipFailureCode = "ZYKH-QSM-PAIR-MEMBERSHIP-FAILURE";
  const membershipFailureHash = crypto.createHash("sha256")
    .update(membershipFailureCode)
    .digest("hex");
  storeFor("device_pairing_codes").set(`pairing-${membershipFailureHash}`, {
    codeHash: membershipFailureHash,
    deviceId: "binding-device-membership-failure",
    role: "CAREGIVER",
    service_user_scopes: ["li-yeye"],
    permissions: ["READ_SAFETY"],
    status: "UNUSED",
    expiresAt: "2099-12-31T23:59:59+08:00",
  });
  currentOpenId = "membership-failure-openid";
  failMembershipSet = true;
  const membershipFailureResult = await cloudFunction.main({
    action: "REDEEM_DEVICE_PAIRING_CODE",
    data: { pairingCode: membershipFailureCode },
  });
  failMembershipSet = false;
  assert.equal(membershipFailureResult.ok, false);
  assert.equal(
    storeFor("device_pairing_codes").get(`pairing-${membershipFailureHash}`).status,
    "UNUSED",
  );
  assert.equal(
    Array.from(storeFor("device_memberships").values())
      .some(row => row.deviceId === "binding-device-membership-failure"),
    false,
  );
  storeFor("device_pairing_codes").delete(`pairing-${membershipFailureHash}`);

  const consumeFailureCode = "ZYKH-QSM-PAIR-CONSUME-FAILURE";
  const consumeFailureHash = crypto.createHash("sha256").update(consumeFailureCode).digest("hex");
  storeFor("device_pairing_codes").set(`pairing-${consumeFailureHash}`, {
    codeHash: consumeFailureHash,
    deviceId: "binding-device-consume-failure",
    role: "CAREGIVER",
    service_user_scopes: ["li-yeye"],
    permissions: ["READ_SAFETY"],
    status: "UNUSED",
    expiresAt: "2099-12-31T23:59:59+08:00",
  });
  currentOpenId = "consume-failure-openid";
  failPairingCodeSet = true;
  const consumeFailureResult = await cloudFunction.main({
    action: "REDEEM_DEVICE_PAIRING_CODE",
    data: { pairingCode: consumeFailureCode },
  });
  failPairingCodeSet = false;
  assert.equal(consumeFailureResult.ok, false);
  assert.equal(
    storeFor("device_pairing_codes").get(`pairing-${consumeFailureHash}`).status,
    "UNUSED",
  );
  assert.equal(
    Array.from(storeFor("device_memberships").values())
      .some(row => row.deviceId === "binding-device-consume-failure"),
    false,
  );
  storeFor("device_pairing_codes").delete(`pairing-${consumeFailureHash}`);

  const pairingHash = "313cbcaa996cfeb1d82bf42258227129db77d12a54bead2641d9a002c0cb3111";
  storeFor("device_pairing_codes").set(`pairing-${pairingHash}`, {
    codeHash: pairingHash,
    deviceId: "binding-device-new",
    role: "CAREGIVER",
    service_user_scopes: ["li-yeye"],
    permissions: ["READ_SAFETY", "READ_INQUIRY", "READ_PLAN"],
    status: "UNUSED",
    expiresAt: "2099-12-31T23:59:59+08:00",
    createdAt: "2026-08-10 10:10:00",
  });
  storeFor("devices").set("binding-device-new", {
    deviceId: "binding-device-new",
    name: "李爷爷家的药箱",
    online: false,
    lastSeenAt: "2026-08-10 10:09:00",
  });
  currentOpenId = "new-caregiver-openid";
  const redeemed = await cloudFunction.main({
    action: "REDEEM_DEVICE_PAIRING_CODE",
    data: {
      pairingCode: "ZYKH-QSM-PAIR-20260810-A1",
      deviceId: "attacker-selected-device",
      role: "OWNER",
      permissions: ["CREATE_COMMAND"],
    },
  });
  assert.deepEqual(redeemed, {
    ok: true,
    deviceId: "binding-device-new",
    role: "CAREGIVER",
    permissions: ["READ_SAFETY", "READ_INQUIRY", "READ_PLAN"],
    serviceUserScopes: ["li-yeye"],
  });
  const devicesAfterRedeem = await cloudFunction.main({ action: "GET_MY_DEVICES", data: {} });
  assert.deepEqual(devicesAfterRedeem.items.map(item => item.deviceId), ["binding-device-new"]);
  const repeatedRedemption = await cloudFunction.main({
    action: "REDEEM_DEVICE_PAIRING_CODE",
    data: { pairingCode: "ZYKH-QSM-PAIR-20260810-A1" },
  });
  assert.equal(repeatedRedemption.ok, false);
  assert.match(repeatedRedemption.error, /PAIRING_CODE_INVALID/);
  const pairingOverHttp = await invokeHttp("REDEEM_DEVICE_PAIRING_CODE", {
    pairingCode: "ZYKH-QSM-PAIR-20260810-A1",
  });
  assert.equal(pairingOverHttp.ok, false);
  assert.match(pairingOverHttp.error, /miniprogram function invocation required/);
  const consumedPairing = storeFor("device_pairing_codes").get(`pairing-${pairingHash}`);
  assert.equal(consumedPairing.status, "CONSUMED");
  assert.equal(consumedPairing.consumedByOpenId, "new-caregiver-openid");
  assert.equal(Object.prototype.hasOwnProperty.call(consumedPairing, "pairingCode"), false);
  assert.equal(Object.prototype.hasOwnProperty.call(consumedPairing, "code"), false);

  currentOpenId = "";
  const devicesWithoutWechatIdentity = await cloudFunction.main({
    action: "GET_MY_DEVICES",
    data: {},
  });
  assert.equal(devicesWithoutWechatIdentity.ok, false);
  assert.match(devicesWithoutWechatIdentity.error, /miniprogram identity required/);
  const redeemWithoutWechatIdentity = await cloudFunction.main({
    action: "REDEEM_DEVICE_PAIRING_CODE",
    data: { pairingCode: "ZYKH-QSM-PAIR-20260810-A1" },
  });
  assert.equal(redeemWithoutWechatIdentity.ok, false);
  assert.match(redeemWithoutWechatIdentity.error, /miniprogram identity required/);

  const racingPairingHash = "75e4a3431a6b252a6d2024c298ef1adbd65fbf797069402e241ca5872c9c9d16";
  storeFor("device_pairing_codes").set(`pairing-${racingPairingHash}`, {
    codeHash: racingPairingHash,
    deviceId: "binding-device-race",
    role: "VIEWER",
    service_user_scopes: [],
    permissions: ["READ_PLAN"],
    status: "UNUSED",
    expiresAt: "2099-12-31T23:59:59+08:00",
  });
  currentOpenId = "pairing-racer-a";
  const racingRedemptionA = cloudFunction.main({
    action: "REDEEM_DEVICE_PAIRING_CODE",
    data: { pairingCode: "ZYKH-QSM-PAIR-RACE-20260810-B2" },
  });
  currentOpenId = "pairing-racer-b";
  const racingRedemptionB = cloudFunction.main({
    action: "REDEEM_DEVICE_PAIRING_CODE",
    data: { pairingCode: "ZYKH-QSM-PAIR-RACE-20260810-B2" },
  });
  const racingResults = await Promise.all([racingRedemptionA, racingRedemptionB]);
  assert.equal(racingResults.filter(result => result.ok === true).length, 1);
  assert.equal(
    racingResults.filter(result => /PAIRING_CODE_INVALID/.test(result.error || "")).length,
    1,
  );
  const racingMemberships = Array.from(storeFor("device_memberships").values())
    .filter(membership => membership.deviceId === "binding-device-race");
  assert.equal(racingMemberships.length, 1);
  assert.equal(racingMemberships[0].status, "ACTIVE");
  const racingPairing = storeFor("device_pairing_codes").get(`pairing-${racingPairingHash}`);
  assert.equal(racingPairing.status, "CONSUMED");
  assert.equal(racingPairing.consumedByOpenId, racingMemberships[0].openid);

  const expiredPairingHash = "e18b74143aa698b91d6b2d4c4e6127f2be734bf65b33814e8ac65bc981a5d8c2";
  storeFor("device_pairing_codes").set(`pairing-${expiredPairingHash}`, {
    codeHash: expiredPairingHash,
    deviceId: "binding-device-expired",
    role: "CAREGIVER",
    permissions: ["READ_SAFETY"],
    status: "UNUSED",
    expiresAt: "2020-01-01T00:00:00+08:00",
  });
  currentOpenId = "expired-code-openid";
  const expiredRedemption = await cloudFunction.main({
    action: "REDEEM_DEVICE_PAIRING_CODE",
    data: { pairingCode: "ZYKH-QSM-PAIR-EXPIRED-20260810-C3" },
  });
  assert.equal(expiredRedemption.ok, false);
  assert.match(expiredRedemption.error, /PAIRING_CODE_INVALID/);
  assert.equal(
    Array.from(storeFor("device_memberships").values())
      .some(membership => membership.deviceId === "binding-device-expired"),
    false,
  );
  assert.equal(
    storeFor("device_pairing_codes").get(`pairing-${expiredPairingHash}`).status,
    "UNUSED",
  );
  currentOpenId = "wechat-openid";

  const safetyEvent = {
    schema_version: 1,
    event_id: "safety-event-blocked-1",
    service_user_id: "wang-nainai",
    person_display_name: "王奶奶",
    medicine: { id: "slot-13-ibuprofen", name: "布洛芬缓释胶囊", slot: 13 },
    occurred_at: "2026-08-10 14:30:00",
    check_status: "BLOCKED",
    dispense_status: "BLOCKED",
    reason_codes: ["CONDITION_CONTRAINDICATION"],
    caregiver_summary: "已检测到登记病史冲突，药箱未出药。",
  };
  const originalSharedSecret = process.env.DEVICE_SECRET;
  const originalDeviceSecrets = process.env.DEVICE_SECRETS;
  delete process.env.DEVICE_SECRET;
  delete process.env.DEVICE_SECRETS;
  const reportWithoutConfiguredSecret = await invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "caller-invented-secret",
    eventId: safetyEvent.event_id,
    payloadDigest: "not-yet-relevant",
    event: safetyEvent,
  });
  assert.equal(reportWithoutConfiguredSecret.ok, false);
  assert.match(reportWithoutConfiguredSecret.error, /device secret is not configured/);
  const heartbeatWithoutConfiguredSecret = await invokeHttp("REPORT_DEVICE", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "caller-invented-secret",
    schemaVersion: 2,
  });
  assert.equal(heartbeatWithoutConfiguredSecret.ok, false);
  assert.match(heartbeatWithoutConfiguredSecret.error, /device secret is not configured/);
  if (originalSharedSecret === undefined) delete process.env.DEVICE_SECRET;
  else process.env.DEVICE_SECRET = originalSharedSecret;
  if (originalDeviceSecrets === undefined) delete process.env.DEVICE_SECRETS;
  else process.env.DEVICE_SECRETS = originalDeviceSecrets;

  process.env.DEVICE_SECRET = "server-test-secret";
  delete process.env.DEVICE_SECRETS;
  const canonicalDigest = "7b5066cad1d4e7da340c0529b312370f83ab99b4285f626a8adcdd33b6916098";
  const reportWithoutDeviceSecret = await cloudFunction.main({
    action: "REPORT_MEDICATION_SAFETY_EVENT",
    data: {
      deviceId: "zykh-qsm-001",
      eventId: safetyEvent.event_id,
      payloadDigest: canonicalDigest,
      event: safetyEvent,
    },
  });
  assert.equal(reportWithoutDeviceSecret.ok, false);
  assert.match(reportWithoutDeviceSecret.error, /unauthorized/);
  assert.equal(storeFor("medication_safety_events").size, 0);

  const reportWithWrongSecret = await invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "wrong-secret",
    eventId: safetyEvent.event_id,
    payloadDigest: canonicalDigest,
    event: safetyEvent,
  });
  assert.equal(reportWithWrongSecret.ok, false);
  assert.match(reportWithWrongSecret.error, /unauthorized/);
  assert.equal(storeFor("medication_safety_events").size, 0);

  const reportWithNonCanonicalDigest = await invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    eventId: safetyEvent.event_id,
    payloadDigest: "0".repeat(64),
    event: safetyEvent,
  });
  assert.equal(reportWithNonCanonicalDigest.ok, false);
  assert.match(reportWithNonCanonicalDigest.error, /PAYLOAD_DIGEST_MISMATCH/);
  assert.equal(storeFor("medication_safety_events").size, 0);

  const eventWriteFailure = Object.assign({}, safetyEvent, {
    event_id: "safety-event-write-failure",
  });
  failSafetyEventSet = true;
  const failedEventWrite = await invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    payloadDigest: canonicalPayloadDigest(eventWriteFailure),
    event: eventWriteFailure,
  });
  failSafetyEventSet = false;
  assert.equal(failedEventWrite.ok, false);
  assert.equal(
    Array.from(storeFor("medication_safety_events").values())
      .some(event => event.eventId === eventWriteFailure.event_id),
    false,
  );

  const firstReport = await invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    payloadDigest: canonicalDigest,
    event: safetyEvent,
  });
  assert.equal(firstReport.ok, true);
  assert.equal(firstReport.eventId, safetyEvent.event_id);
  assert.equal(firstReport.payloadDigest, canonicalDigest);
  assert.equal(firstReport.replay, false);

  failSafetyEventGet = true;
  const transientReadFailure = await invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    payloadDigest: canonicalDigest,
    event: safetyEvent,
  });
  failSafetyEventGet = false;
  assert.equal(transientReadFailure.ok, false);
  assert.equal(storeFor("medication_safety_events").size, 1);

  const reorderedSafetyEvent = {
    service_user_id: safetyEvent.service_user_id,
    reason_codes: safetyEvent.reason_codes,
    person_display_name: safetyEvent.person_display_name,
    occurred_at: safetyEvent.occurred_at,
    medicine: { slot: 13, name: "布洛芬缓释胶囊", id: "slot-13-ibuprofen" },
    event_id: safetyEvent.event_id,
    dispense_status: safetyEvent.dispense_status,
    check_status: safetyEvent.check_status,
    caregiver_summary: safetyEvent.caregiver_summary,
    schema_version: safetyEvent.schema_version,
  };
  const replayedReport = await invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    eventId: safetyEvent.event_id,
    payloadDigest: canonicalDigest,
    event: reorderedSafetyEvent,
  });
  assert.equal(replayedReport.ok, true);
  assert.equal(replayedReport.replay, true);

  const conflictingEvent = Object.assign({}, safetyEvent, {
    caregiver_summary: "已篡改的冲突摘要。",
  });
  const conflictingReport = await invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    eventId: safetyEvent.event_id,
    payloadDigest: "d2167a3020269d3c62f9abb5fb9d364ded9909fdc66b30e44a54cc1d54cbf5f6",
    event: conflictingEvent,
  });
  assert.equal(conflictingReport.ok, false);
  assert.match(conflictingReport.error, /IDEMPOTENCY_CONFLICT/);
  assert.equal(storeFor("medication_safety_events").size, 1);

  storeFor("device_memberships").set("membership-notification-a", {
    openid: "notification-openid-a",
    deviceId: "notification-device",
    role: "CAREGIVER",
    service_user_scopes: ["wang-nainai"],
    permissions: ["READ_SAFETY"],
    status: "ACTIVE",
  });
  storeFor("device_memberships").set("membership-notification-b", {
    openid: "notification-openid-b",
    deviceId: "notification-device",
    role: "OWNER",
    service_user_scopes: [],
    permissions: ["READ_SAFETY"],
    status: "ACTIVE",
  });
  storeFor("device_memberships").set("membership-notification-out-of-scope", {
    openid: "notification-openid-out-of-scope",
    deviceId: "notification-device",
    role: "CAREGIVER",
    service_user_scopes: ["li-yeye"],
    permissions: ["READ_SAFETY"],
    status: "ACTIVE",
  });
  storeFor("device_memberships").set("membership-notification-no-permission", {
    openid: "notification-openid-no-permission",
    deviceId: "notification-device",
    role: "VIEWER",
    permissions: ["READ_PLAN"],
    status: "ACTIVE",
  });
  storeFor("device_memberships").set("membership-notification-revoked", {
    openid: "notification-openid-revoked",
    deviceId: "notification-device",
    role: "CAREGIVER",
    permissions: ["READ_SAFETY"],
    status: "REVOKED",
  });
  const notificationEvent = {
    schema_version: 1,
    event_id: "safety-event-notification-1",
    service_user_id: "wang-nainai",
    occurred_at: "2026-08-10 18:00:00",
    check_status: "BLOCKED",
    dispense_status: "BLOCKED",
    reason_codes: ["CONDITION_CONTRAINDICATION"],
    caregiver_summary: "药箱已阻止本次取药，请打开小程序查看。",
  };
  failSafetyReceiptSet = true;
  const failedReceiptWrite = await invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
    deviceId: "notification-device",
    deviceSecret: "server-test-secret",
    payloadDigest: "34e66ad9157c031e671d925d4b4c4eaa4a78199709175fef6d511052bcb1c5c9",
    event: notificationEvent,
  });
  failSafetyReceiptSet = false;
  assert.equal(failedReceiptWrite.ok, false);
  assert.equal(storeFor("caregiver_event_receipts").size, 0);
  assert.equal(storeFor("caregiver_notification_outbox").size, 0);

  failSafetyNotificationSet = true;
  const failedNotificationWrite = await invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
    deviceId: "notification-device",
    deviceSecret: "server-test-secret",
    payloadDigest: "34e66ad9157c031e671d925d4b4c4eaa4a78199709175fef6d511052bcb1c5c9",
    event: notificationEvent,
  });
  failSafetyNotificationSet = false;
  assert.equal(failedNotificationWrite.ok, false);
  assert.equal(storeFor("caregiver_event_receipts").size, 0);
  assert.equal(storeFor("caregiver_notification_outbox").size, 0);

  const notificationReport = await invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
    deviceId: "notification-device",
    deviceSecret: "server-test-secret",
    payloadDigest: "34e66ad9157c031e671d925d4b4c4eaa4a78199709175fef6d511052bcb1c5c9",
    event: notificationEvent,
  });
  assert.equal(notificationReport.ok, true);
  const notificationRows = Array.from(storeFor("caregiver_notification_outbox").values());
  assert.equal(notificationRows.length, 2);
  assert.deepEqual(
    notificationRows.map(row => row.recipientOpenId).sort(),
    ["notification-openid-a", "notification-openid-b"],
  );
  notificationRows.forEach(row => {
    assert.equal(row.deviceId, "notification-device");
    assert.equal(row.eventId, notificationEvent.event_id);
    assert.equal(row.type, "MEDICATION_SAFETY_EVENT");
    assert.equal(row.state, "PENDING");
    assert.equal(row.attempts, 0);
    assert.equal(row.templateKey, "MEDICATION_SAFETY_ALERT");
    for (const forbiddenField of [
      "medicine",
      "medicineName",
      "personName",
      "reasonCodes",
      "summary",
      "caregiverSummary",
    ]) {
      assert.equal(Object.prototype.hasOwnProperty.call(row, forbiddenField), false);
    }
  });
  const replayedNotificationReport = await invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
    deviceId: "notification-device",
    deviceSecret: "server-test-secret",
    payloadDigest: "34e66ad9157c031e671d925d4b4c4eaa4a78199709175fef6d511052bcb1c5c9",
    event: notificationEvent,
  });
  assert.equal(replayedNotificationReport.ok, true);
  assert.equal(replayedNotificationReport.replay, true);
  assert.equal(storeFor("caregiver_notification_outbox").size, 2);
  for (const [id, receipt] of storeFor("caregiver_event_receipts")) {
    if (receipt.deviceId === "notification-device") {
      storeFor("caregiver_event_receipts").delete(id);
    }
  }

  const listWithoutMembership = await cloudFunction.main({
    action: "LIST_MEDICATION_SAFETY_EVENTS",
    data: { deviceId: "zykh-qsm-001", limit: 20 },
  });
  assert.equal(listWithoutMembership.ok, false);
  assert.match(listWithoutMembership.error, /CAREGIVER_MEMBERSHIP_REQUIRED/);

  storeFor("device_memberships").set("membership-caregiver-a", {
    openid: "wechat-openid",
    deviceId: "zykh-qsm-001",
    role: "CAREGIVER",
    service_user_scopes: ["wang-nainai"],
    permissions: [
      "READ_SAFETY",
      "READ_INQUIRY",
      "READ_PLAN",
      "READ_PROFILE",
      "READ_RECORD",
      "READ_VITALS",
      "READ_MEDICINE",
      "CREATE_COMMAND",
    ],
    status: "ACTIVE",
  });
  storeFor("device_memberships").set("membership-viewer-no-safety", {
    openid: "viewer-openid",
    deviceId: "zykh-qsm-001",
    role: "VIEWER",
    permissions: ["READ_PLAN"],
    status: "ACTIVE",
  });
  storeFor("device_memberships").set("membership-empty-permissions", {
    openid: "empty-permissions-openid",
    deviceId: "zykh-qsm-001",
    role: "VIEWER",
    permissions: [],
    status: "ACTIVE",
  });
  currentOpenId = "stranger-openid";
  const medicinesWithoutMembership = await cloudFunction.main({
    action: "LIST_MEDICINES",
    data: { deviceId: "zykh-qsm-001", limit: 20 },
  });
  assert.equal(medicinesWithoutMembership.ok, false);
  assert.match(medicinesWithoutMembership.error, /CAREGIVER_MEMBERSHIP_REQUIRED/);

  currentOpenId = "viewer-openid";
  const viewerCommand = await cloudFunction.main({
    action: "CREATE_COMMAND",
    data: { deviceId: "zykh-qsm-001", type: "AUDIO_BEEP", payload: {} },
  });
  assert.equal(viewerCommand.ok, false);
  assert.match(viewerCommand.error, /CAREGIVER_PERMISSION_DENIED/);
  assert.equal(inserted, 0);

  const listWithoutSafetyPermission = await cloudFunction.main({
    action: "LIST_MEDICATION_SAFETY_EVENTS",
    data: { deviceId: "zykh-qsm-001", limit: 20 },
  });
  assert.equal(listWithoutSafetyPermission.ok, false);
  assert.match(listWithoutSafetyPermission.error, /CAREGIVER_PERMISSION_DENIED/);

  const inquiryWithoutInquiryPermission = await cloudFunction.main({
    action: "LIST_INQUIRIES",
    data: { deviceId: "zykh-qsm-001", limit: 20 },
  });
  assert.equal(inquiryWithoutInquiryPermission.ok, false);
  assert.match(inquiryWithoutInquiryPermission.error, /CAREGIVER_PERMISSION_DENIED/);

  const inquiryDetailWithoutInquiryPermission = await cloudFunction.main({
    action: "GET_INQUIRY_DETAIL",
    data: { deviceId: "zykh-qsm-001", inquiryId: "not-visible" },
  });
  assert.equal(inquiryDetailWithoutInquiryPermission.ok, false);
  assert.match(inquiryDetailWithoutInquiryPermission.error, /CAREGIVER_PERMISSION_DENIED/);

  const recordsWithoutRecordPermission = await cloudFunction.main({
    action: "LIST_RECORDS",
    data: { deviceId: "zykh-qsm-001", limit: 20 },
  });
  assert.equal(recordsWithoutRecordPermission.ok, false);
  assert.match(recordsWithoutRecordPermission.error, /CAREGIVER_PERMISSION_DENIED/);

  const vitalsWithoutVitalsPermission = await cloudFunction.main({
    action: "LIST_VITALS",
    data: { deviceId: "zykh-qsm-001", limit: 20 },
  });
  assert.equal(vitalsWithoutVitalsPermission.ok, false);
  assert.match(vitalsWithoutVitalsPermission.error, /CAREGIVER_PERMISSION_DENIED/);

  const medicinesWithoutMedicinePermission = await cloudFunction.main({
    action: "LIST_MEDICINES",
    data: { deviceId: "zykh-qsm-001", limit: 20 },
  });
  assert.equal(medicinesWithoutMedicinePermission.ok, false);
  assert.match(medicinesWithoutMedicinePermission.error, /CAREGIVER_PERMISSION_DENIED/);

  const commandsWithoutCommandPermission = await cloudFunction.main({
    action: "LIST_COMMANDS",
    data: { deviceId: "zykh-qsm-001", limit: 20 },
  });
  assert.equal(commandsWithoutCommandPermission.ok, false);
  assert.match(commandsWithoutCommandPermission.error, /CAREGIVER_PERMISSION_DENIED/);

  storeFor("device_memberships").set("membership-revoked", {
    openid: "revoked-openid",
    deviceId: "zykh-qsm-001",
    permissions: ["READ_SAFETY"],
    status: "REVOKED",
  });
  currentOpenId = "revoked-openid";
  const revokedMembershipList = await cloudFunction.main({
    action: "LIST_MEDICATION_SAFETY_EVENTS",
    data: { deviceId: "zykh-qsm-001", limit: 20 },
  });
  assert.equal(revokedMembershipList.ok, false);
  assert.match(revokedMembershipList.error, /CAREGIVER_MEMBERSHIP_REQUIRED/);
  currentOpenId = "wechat-openid";

  const authorizedList = await cloudFunction.main({
    action: "LIST_MEDICATION_SAFETY_EVENTS",
    data: { deviceId: "zykh-qsm-001", personId: "wang-nainai", limit: 20 },
  });
  assert.equal(authorizedList.ok, true);
  assert.equal(authorizedList.items.length, 1);
  assert.deepEqual(authorizedList.items[0], {
    eventId: "safety-event-blocked-1",
    personId: "wang-nainai",
    personName: "王奶奶",
    medicineId: "slot-13-ibuprofen",
    medicineName: "布洛芬缓释胶囊",
    slot: 13,
    checkStatus: "BLOCKED",
    dispenseStatus: "BLOCKED",
    summary: "已检测到登记病史冲突，药箱未出药。",
    occurredAt: "2026-08-10 14:30:00",
    read: false,
  });
  assert.equal(authorizedList.nextCursor, "");

  storeFor("records").set("record-wang", {
    deviceId: "zykh-qsm-001",
    target_user_id: "wang-nainai",
    createdAt: "2026-08-10 15:00:00",
  });
  storeFor("records").set("record-li", {
    deviceId: "zykh-qsm-001",
    target_user_id: "li-yeye",
    createdAt: "2026-08-10 15:01:00",
  });
  storeFor("inquiries").set("inquiry-wang", {
    deviceId: "zykh-qsm-001",
    user_id: "wang-nainai",
    inquiry_id: "inquiry-wang",
    updatedAt: "2026-08-10 15:00:00",
  });
  storeFor("inquiries").set("inquiry-li", {
    deviceId: "zykh-qsm-001",
    user_id: "li-yeye",
    inquiry_id: "inquiry-li",
    updatedAt: "2026-08-10 15:01:00",
  });
  storeFor("vitals").set("vitals-wang", {
    deviceId: "zykh-qsm-001",
    service_user_id: "wang-nainai",
    heartRate: 72,
    createdAt: "2026-08-10 15:00:00",
  });
  storeFor("vitals").set("vitals-li", {
    deviceId: "zykh-qsm-001",
    service_user_id: "li-yeye",
    heartRate: 75,
    createdAt: "2026-08-10 15:01:00",
  });
  storeFor("service_users").set("user-wang", {
    deviceId: "zykh-qsm-001",
    id: "wang-nainai",
    updatedAt: "2026-08-10 15:00:00",
  });
  storeFor("service_users").set("user-li", {
    deviceId: "zykh-qsm-001",
    id: "li-yeye",
    updatedAt: "2026-08-10 15:01:00",
  });
  storeFor("today_plans").set("plan-wang", {
    deviceId: "zykh-qsm-001",
    service_user_id: "wang-nainai",
    updatedAt: "2026-08-10 15:00:00",
  });
  storeFor("today_plans").set("plan-li", {
    deviceId: "zykh-qsm-001",
    service_user_id: "li-yeye",
    updatedAt: "2026-08-10 15:01:00",
  });
  storeFor("devices").set("zykh-qsm-001", {
    deviceId: "zykh-qsm-001",
    online: true,
    deviceSecret: "must-not-leak",
    syncSummary: {
      counts: { serviceUsers: 2, plans: 2, inquiries: 2 },
      serviceUsers: [
        { id: "wang-nainai", name: "王奶奶" },
        { id: "li-yeye", name: "李爷爷" },
      ],
      plans: [
        { id: "plan-wang", service_user_id: "wang-nainai" },
        { id: "plan-li", service_user_id: "li-yeye" },
      ],
      recentInquiries: [
        { inquiry_id: "inquiry-wang", target_user_id: "wang-nainai" },
        { inquiry_id: "inquiry-li", target_user_id: "li-yeye" },
      ],
    },
  });

  currentOpenId = "viewer-openid";
  const planOnlySnapshot = await cloudFunction.main({
    action: "GET_SNAPSHOT",
    data: { deviceId: "zykh-qsm-001" },
  });
  assert.deepEqual(Object.keys(planOnlySnapshot), ["plans"]);
  assert.deepEqual(
    planOnlySnapshot.plans.map(row => row.service_user_id).sort(),
    ["li-yeye", "wang-nainai"],
  );
  const planOnlyDevice = await cloudFunction.main({
    action: "GET_DEVICE",
    data: { deviceId: "zykh-qsm-001" },
  });
  assert.deepEqual(Object.keys(planOnlyDevice.syncSummary).sort(), ["counts", "plans"]);
  assert.deepEqual(planOnlyDevice.syncSummary.counts, { plans: 2 });
  assert.deepEqual(
    planOnlyDevice.syncSummary.plans.map(row => row.service_user_id).sort(),
    ["li-yeye", "wang-nainai"],
  );

  currentOpenId = "empty-permissions-openid";
  const emptyPermissionSnapshot = await cloudFunction.main({
    action: "GET_SNAPSHOT",
    data: { deviceId: "zykh-qsm-001" },
  });
  assert.deepEqual(emptyPermissionSnapshot, {});
  const emptyPermissionDevice = await cloudFunction.main({
    action: "GET_DEVICE",
    data: { deviceId: "zykh-qsm-001" },
  });
  assert.equal(emptyPermissionDevice.online, true);
  assert.equal(emptyPermissionDevice.deviceSecret, undefined);
  assert.deepEqual(emptyPermissionDevice.syncSummary, { counts: {} });
  const emptyPermissionRecords = await cloudFunction.main({
    action: "LIST_RECORDS",
    data: { deviceId: "zykh-qsm-001", limit: 20 },
  });
  assert.equal(emptyPermissionRecords.ok, false);
  assert.match(emptyPermissionRecords.error, /CAREGIVER_PERMISSION_DENIED/);

  currentOpenId = "wechat-openid";

  const scopedRecords = await cloudFunction.main({
    action: "LIST_RECORDS",
    data: { deviceId: "zykh-qsm-001", limit: 20 },
  });
  assert.deepEqual(scopedRecords.map(row => row.target_user_id), ["wang-nainai"]);
  const scopedInquiries = await cloudFunction.main({
    action: "LIST_INQUIRIES",
    data: { deviceId: "zykh-qsm-001", limit: 20 },
  });
  assert.deepEqual(
    scopedInquiries.map(row => row.user_id || row.target_user_id),
    ["wang-nainai"],
  );
  const scopedVitals = await cloudFunction.main({
    action: "LIST_VITALS",
    data: { deviceId: "zykh-qsm-001", limit: 20 },
  });
  assert.deepEqual(scopedVitals.map(row => row.service_user_id), ["wang-nainai"]);
  const scopedLatestVitals = await cloudFunction.main({
    action: "GET_LATEST_VITALS",
    data: { deviceId: "zykh-qsm-001" },
  });
  assert.equal(scopedLatestVitals.service_user_id, "wang-nainai");
  const scopedInquiryDetail = await cloudFunction.main({
    action: "GET_INQUIRY_DETAIL",
    data: { deviceId: "zykh-qsm-001", inquiryId: "inquiry-wang" },
  });
  assert.equal(scopedInquiryDetail.inquiry_id, "inquiry-wang");
  const hiddenInquiryDetail = await cloudFunction.main({
    action: "GET_INQUIRY_DETAIL",
    data: { deviceId: "zykh-qsm-001", inquiryId: "inquiry-li" },
  });
  assert.equal(hiddenInquiryDetail.ok, false);
  assert.match(hiddenInquiryDetail.error, /NOT_FOUND/);
  const scopedSnapshot = await cloudFunction.main({
    action: "GET_SNAPSHOT",
    data: { deviceId: "zykh-qsm-001" },
  });
  assert.deepEqual(scopedSnapshot.serviceUsers.map(row => row.id), ["wang-nainai"]);
  assert.deepEqual(
    scopedSnapshot.plans.map(row => row.service_user_id),
    ["wang-nainai"],
  );
  assert.deepEqual(
    scopedSnapshot.inquiries.map(row => row.user_id || row.target_user_id),
    ["wang-nainai"],
  );
  assert.deepEqual(
    scopedSnapshot.vitals.map(row => row.service_user_id),
    ["wang-nainai"],
  );
  const scopedDevice = await cloudFunction.main({
    action: "GET_DEVICE",
    data: { deviceId: "zykh-qsm-001" },
  });
  assert.deepEqual(scopedDevice.syncSummary.serviceUsers.map(row => row.id), ["wang-nainai"]);
  assert.deepEqual(scopedDevice.syncSummary.plans.map(row => row.service_user_id), ["wang-nainai"]);
  assert.deepEqual(
    scopedDevice.syncSummary.recentInquiries.map(row => row.target_user_id),
    ["wang-nainai"],
  );
  assert.deepEqual(scopedDevice.syncSummary.counts, {
    serviceUsers: 1,
    plans: 1,
    inquiries: 1,
  });

  storeFor("records").clear();
  for (let index = 0; index < 101; index += 1) {
    storeFor("records").set(`record-li-newer-${index}`, {
      deviceId: "zykh-qsm-001",
      target_user_id: "li-yeye",
      createdAt: `2026-09-${String((index % 28) + 1).padStart(2, "0")} 16:${String(index % 60).padStart(2, "0")}:00`,
    });
  }
  storeFor("records").set("record-wang-after-first-page", {
    deviceId: "zykh-qsm-001",
    target_user_id: "wang-nainai",
    createdAt: "2025-01-01 00:00:00",
  });
  const scopedRecordAfterFirstPage = await cloudFunction.main({
    action: "LIST_RECORDS",
    data: { deviceId: "zykh-qsm-001", limit: 1 },
  });
  assert.equal(scopedRecordAfterFirstPage.length, 1);
  assert.equal(scopedRecordAfterFirstPage[0]._id, "record-wang-after-first-page");

  storeFor("inquiries").clear();
  const deviceDocument = storeFor("devices").get("zykh-qsm-001");
  deviceDocument.syncSummary.recentInquiries = [];
  for (let index = 0; index < 101; index += 1) {
    storeFor("inquiries").set(`inquiry-li-newer-${index}`, {
      deviceId: "zykh-qsm-001",
      user_id: "li-yeye",
      inquiry_id: `inquiry-li-newer-${index}`,
      updatedAt: `2026-09-${String((index % 28) + 1).padStart(2, "0")} 16:${String(index % 60).padStart(2, "0")}:00`,
    });
  }
  storeFor("inquiries").set("inquiry-wang-after-first-page", {
    deviceId: "zykh-qsm-001",
    user_id: "wang-nainai",
    inquiry_id: "inquiry-wang-after-first-page",
    updatedAt: "2025-01-01 00:00:00",
  });
  const scopedInquiryAfterFirstPage = await cloudFunction.main({
    action: "LIST_INQUIRIES",
    data: { deviceId: "zykh-qsm-001", limit: 1 },
  });
  assert.equal(scopedInquiryAfterFirstPage.length, 1);
  assert.equal(scopedInquiryAfterFirstPage[0].inquiry_id, "inquiry-wang-after-first-page");

  const commandsBeforeOutOfScopeWrite = storeFor("commands").size;
  for (const [type, payload] of [
    ["AI_CHAT", { target_user_id: "li-yeye", question: "范围外问询" }],
    ["UPSERT_SERVICE_USER", { id: "li-yeye", name: "不应修改" }],
    ["UPSERT_TODAY_PLAN", { service_user_id: "li-yeye", id: "plan-li" }],
  ]) {
    const rejected = await cloudFunction.main({
      action: "CREATE_COMMAND",
      data: { deviceId: "zykh-qsm-001", type, payload },
    });
    assert.equal(rejected.ok, false);
    assert.match(rejected.error, /NOT_FOUND|CAREGIVER_PERMISSION_DENIED/);
  }
  assert.equal(storeFor("commands").size, commandsBeforeOutOfScopeWrite);

  currentOpenId = "stranger-openid";
  const detailWithoutMembership = await cloudFunction.main({
    action: "GET_MEDICATION_SAFETY_EVENT",
    data: { deviceId: "zykh-qsm-001", eventId: safetyEvent.event_id },
  });
  assert.equal(detailWithoutMembership.ok, false);
  assert.match(detailWithoutMembership.error, /CAREGIVER_MEMBERSHIP_REQUIRED/);
  currentOpenId = "wechat-openid";

  const authorizedDetail = await cloudFunction.main({
    action: "GET_MEDICATION_SAFETY_EVENT",
    data: { deviceId: "zykh-qsm-001", eventId: safetyEvent.event_id },
  });
  assert.equal(authorizedDetail.ok, true);
  assert.equal(authorizedDetail.event.eventId, safetyEvent.event_id);
  assert.deepEqual(authorizedDetail.event.reasonCodes, ["CONDITION_CONTRAINDICATION"]);
  assert.equal(authorizedDetail.event.profileRevision, 0);
  assert.equal(authorizedDetail.event.rulesetVersion, "");
  assert.equal(authorizedDetail.event.medicineReviewFingerprint, "");
  assert.equal(authorizedDetail.event.qsmOperationId, "");

  assert.equal(authorizedDetail.event.read, false, "opening detail must not mark the event read");

  const collidingDocumentIdDetail = await cloudFunction.main({
    action: "GET_MEDICATION_SAFETY_EVENT",
    data: { deviceId: "zykh-qsm-001", eventId: "safety:event:blocked:1" },
  });
  assert.equal(collidingDocumentIdDetail.ok, false);
  assert.match(collidingDocumentIdDetail.error, /NOT_FOUND/);

  const storedEventBeforeRead = JSON.stringify(
    storeFor("medication_safety_events").get("zykh-qsm-001-safety-event-blocked-1"),
  );
  const commandsBeforeRead = storeFor("commands").size;
  const firstMarkRead = await cloudFunction.main({
    action: "MARK_MEDICATION_SAFETY_EVENT_READ",
    data: { deviceId: "zykh-qsm-001", eventId: safetyEvent.event_id },
  });
  assert.equal(firstMarkRead.ok, true);
  assert.equal(firstMarkRead.eventId, safetyEvent.event_id);
  assert.equal(firstMarkRead.state, "READ");
  assert.equal(firstMarkRead.replay, false);
  assert.match(firstMarkRead.readAt, /^\d{4}-\d{2}-\d{2} /);
  assert.equal(storeFor("caregiver_event_receipts").size, 1);

  const repeatedMarkRead = await cloudFunction.main({
    action: "MARK_MEDICATION_SAFETY_EVENT_READ",
    data: { deviceId: "zykh-qsm-001", eventId: safetyEvent.event_id },
  });
  assert.equal(repeatedMarkRead.ok, true);
  assert.equal(repeatedMarkRead.replay, true);
  assert.equal(repeatedMarkRead.readAt, firstMarkRead.readAt, "first read_at must be immutable");
  assert.equal(storeFor("caregiver_event_receipts").size, 1);
  assert.equal(
    JSON.stringify(storeFor("medication_safety_events").get("zykh-qsm-001-safety-event-blocked-1")),
    storedEventBeforeRead,
    "mark-read must not mutate append-only safety events",
  );
  assert.equal(storeFor("commands").size, commandsBeforeRead, "mark-read must not enqueue a command");

  const detailAfterRead = await cloudFunction.main({
    action: "GET_MEDICATION_SAFETY_EVENT",
    data: { deviceId: "zykh-qsm-001", eventId: safetyEvent.event_id },
  });
  assert.equal(detailAfterRead.event.read, true);

  const secondSafetyEvent = {
    schema_version: 1,
    event_id: "safety-event-passed-2",
    service_user_id: "wang-nainai",
    service_user_name: "王奶奶",
    medicine_id: "slot-3-smecta",
    medicine_name: "蒙脱石散",
    slot: "3",
    occurred_at: "2026-08-10 15:00:00",
    check_status: "PASSED",
    dispense_status: "DISPENSED",
    reason_codes: [],
    reason_summary: "安全核查通过，已完成取药。",
  };
  const secondDigest = "77941f9f74a6fdb101788695297d70fc0e6650f000cf06df041cf237c3da5ca0";
  const secondReport = await invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    eventId: secondSafetyEvent.event_id,
    payloadDigest: secondDigest,
    event: secondSafetyEvent,
  });
  assert.equal(secondReport.ok, true);
  assert.equal(secondReport.replay, false);
  assert.equal(storeFor("caregiver_event_receipts").size, 2);
  const secondReceipt = Array.from(storeFor("caregiver_event_receipts").values())
    .find(receipt => receipt.eventId === secondSafetyEvent.event_id);
  assert.equal(secondReceipt.state, "UNREAD");

  const replayedSecondReport = await invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    eventId: secondSafetyEvent.event_id,
    payloadDigest: secondDigest,
    event: secondSafetyEvent,
  });
  assert.equal(replayedSecondReport.replay, true);
  assert.equal(storeFor("caregiver_event_receipts").size, 2);
  assert.equal(secondReceipt.state, "UNREAD");

  const unreadList = await cloudFunction.main({
    action: "LIST_MEDICATION_SAFETY_EVENTS",
    data: { deviceId: "zykh-qsm-001", unreadOnly: true, limit: 20 },
  });
  assert.equal(unreadList.ok, true);
  assert.deepEqual(unreadList.items.map(item => item.eventId), [secondSafetyEvent.event_id]);
  assert.equal(unreadList.items[0].personName, "王奶奶");
  assert.equal(unreadList.items[0].medicineName, "蒙脱石散");
  assert.equal(unreadList.items[0].slot, 3);
  assert.equal(unreadList.items[0].summary, "安全核查通过，已完成取药。");

  const safetyStore = storeFor("medication_safety_events");
  for (let number = 3; number <= 103; number += 1) {
    const eventId = `safety-event-bulk-${String(number).padStart(3, "0")}`;
    safetyStore.set(`zykh-qsm-001-${eventId}`, {
      deviceId: "zykh-qsm-001",
      eventId,
      event_id: eventId,
      service_user_id: "wang-nainai",
      person_display_name: "王奶奶",
      medicine: { id: "bulk-medicine", name: "历史用药", slot: 1 },
      occurred_at: "2026-08-10 12:00:00",
      check_status: "BLOCKED",
      dispense_status: "BLOCKED",
      caregiver_summary: `历史安全事件 ${number}`,
    });
  }
  safetyStore.set("zykh-qsm-001-safety-event-private-li", {
    deviceId: "zykh-qsm-001",
    eventId: "safety-event-private-li",
    event_id: "safety-event-private-li",
    service_user_id: "li-yeye",
    person_display_name: "李爷爷",
    medicine: { id: "private-medicine", name: "不可见药品", slot: 2 },
    occurred_at: "2026-08-10 16:00:00",
    check_status: "BLOCKED",
    dispense_status: "BLOCKED",
    caregiver_summary: "越权人物事件不可见",
  });

  const outOfScopeList = await cloudFunction.main({
    action: "LIST_MEDICATION_SAFETY_EVENTS",
    data: { deviceId: "zykh-qsm-001", personId: "li-yeye", limit: 20 },
  });
  assert.equal(outOfScopeList.ok, false);
  assert.match(outOfScopeList.error, /NOT_FOUND/);
  const receiptsBeforePrivateAccess = storeFor("caregiver_event_receipts").size;
  for (const action of [
    "GET_MEDICATION_SAFETY_EVENT",
    "MARK_MEDICATION_SAFETY_EVENT_READ",
  ]) {
    const privateAccess = await cloudFunction.main({
      action,
      data: { deviceId: "zykh-qsm-001", eventId: "safety-event-private-li" },
    });
    assert.equal(privateAccess.ok, false);
    assert.match(privateAccess.error, /NOT_FOUND/);
  }
  assert.equal(storeFor("caregiver_event_receipts").size, receiptsBeforePrivateAccess);

  const pagedEventIds = [];
  let cursor = "";
  const pageSizes = [];
  do {
    const page = await cloudFunction.main({
      action: "LIST_MEDICATION_SAFETY_EVENTS",
      data: { deviceId: "zykh-qsm-001", limit: 500, cursor },
    });
    assert.equal(page.ok, true);
    assert.equal(page.items.length <= 50, true, "LIST must enforce its public maximum");
    pageSizes.push(page.items.length);
    pagedEventIds.push(...page.items.map(item => item.eventId));
    cursor = page.nextCursor;
  } while (cursor && pageSizes.length < 10);
  assert.deepEqual(pageSizes, [50, 50, 3]);
  assert.equal(pagedEventIds.length, 103, "cursor pagination must retain histories beyond 100 rows");
  assert.equal(new Set(pagedEventIds).size, 103, "stable cursor pages must not overlap");
  assert.equal(pagedEventIds.includes("safety-event-private-li"), false);

  storeFor("medication_safety_events").set("zykh-qsm-001-safety-event-corrupt-1", {
    eventId: "safety-event-corrupt-1",
    deviceId: "zykh-qsm-001",
    service_user_id: "wang-nainai",
    check_status: "CORRUPT",
    dispense_status: "MAYBE_OPENED",
    occurred_at: "2026-08-10 15:30:00",
  });
  const corruptDetail = await cloudFunction.main({
    action: "GET_MEDICATION_SAFETY_EVENT",
    data: { deviceId: "zykh-qsm-001", eventId: "safety-event-corrupt-1" },
  });
  assert.equal(corruptDetail.ok, true);
  assert.equal(corruptDetail.event.personName, "家庭成员");
  assert.equal(corruptDetail.event.medicineName, "未命名药品");
  assert.equal(corruptDetail.event.checkStatus, "CHECK_FAILED");
  assert.equal(corruptDetail.event.dispenseStatus, "NOT_STARTED");

  const eventsBeforeFinalize = JSON.stringify(Array.from(safetyStore.entries()));
  const rejectedSafetyFinalize = await invokeHttp("FINALIZE_SNAPSHOT", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    kind: "medicationSafetyEvents",
    ids: [],
  });
  assert.equal(rejectedSafetyFinalize.ok, false);
  assert.match(rejectedSafetyFinalize.error, /unsupported snapshot kind/);
  const ordinaryFinalize = await invokeHttp("FINALIZE_SNAPSHOT", {
    deviceId: "zykh-qsm-001",
    deviceSecret: "server-test-secret",
    kind: "records",
    ids: [],
  });
  assert.equal(ordinaryFinalize.removed, 0);
  assert.equal(JSON.stringify(Array.from(safetyStore.entries())), eventsBeforeFinalize);

  const commandsBeforeForbiddenSafetyActions = storeFor("commands").size;
  for (const action of [
    "APPROVE_MEDICATION",
    "REJECT_MEDICATION",
    "UNBLOCK_MEDICATION",
    "SUBMIT_MEDICATION_DECISION",
    "OPEN_FROM_SAFETY_EVENT",
  ]) {
    const rejected = await cloudFunction.main({
      action,
      data: { deviceId: "zykh-qsm-001", eventId: safetyEvent.event_id },
    });
    assert.equal(rejected.ok, false);
    assert.match(rejected.error, /unknown action/);
  }
  assert.equal(storeFor("commands").size, commandsBeforeForbiddenSafetyActions);

  const raceEventA = {
    event_id: "safety-event-race-1",
    service_user_id: "wang-nainai",
    occurred_at: "2026-08-10 17:00:00",
    check_status: "BLOCKED",
    dispense_status: "BLOCKED",
    reason_summary: "并发版本 A",
  };
  const raceEventB = Object.assign({}, raceEventA, { reason_summary: "并发版本 B" });
  const concurrentReports = await Promise.all([
    invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
      deviceId: "zykh-qsm-race",
      deviceSecret: "server-test-secret",
      payloadDigest: "9155b5d40ca60109e22b35911f99c3e1ef8f865c8b2acdae81b3ee3fedbb63b3",
      event: raceEventA,
    }),
    invokeHttp("REPORT_MEDICATION_SAFETY_EVENT", {
      deviceId: "zykh-qsm-race",
      deviceSecret: "server-test-secret",
      payloadDigest: "bf4b455945cd7612eea1be77061756ea0585d5c03b9c048c5bc8da3e11efaf35",
      event: raceEventB,
    }),
  ]);
  assert.equal(concurrentReports.filter(result => result.ok === true).length, 1);
  assert.equal(concurrentReports.filter(result => /IDEMPOTENCY_CONFLICT/.test(result.error || "")).length, 1);

  if (originalSharedSecret === undefined) delete process.env.DEVICE_SECRET;
  else process.env.DEVICE_SECRET = originalSharedSecret;
  if (originalDeviceSecrets === undefined) delete process.env.DEVICE_SECRETS;
  else process.env.DEVICE_SECRETS = originalDeviceSecrets;

  const httpResult = await cloudFunction.main({
    httpMethod: "POST",
    body: JSON.stringify({
      action: "CREATE_COMMAND",
      data: { deviceId: "zykh-qsm-001", type: "AUDIO_BEEP", payload: {} },
    }),
  });
  const httpBody = JSON.parse(httpResult.body);
  assert.equal(httpBody.ok, false);
  assert.match(httpBody.error, /miniprogram function invocation required/);
  assert.equal(inserted, 0);

  const eventResult = await cloudFunction.main({
    action: "CREATE_COMMAND",
    data: { deviceId: "zykh-qsm-001", type: "AUDIO_BEEP", payload: {} },
  });
  assert.equal(eventResult.status, "pending");
  assert.equal(eventResult.sourceOpenId, "wechat-openid");
  assert.equal(inserted, 1);

  const idempotentCommand = {
    deviceId: "zykh-qsm-001",
    type: "AUDIO_BEEP",
    requestId: "stable-command-request",
    payload: { count: 1 },
  };
  const firstIdempotentCommand = await cloudFunction.main({
    action: "CREATE_COMMAND",
    data: idempotentCommand,
  });
  const replayedIdempotentCommand = await cloudFunction.main({
    action: "CREATE_COMMAND",
    data: idempotentCommand,
  });
  assert.equal(replayedIdempotentCommand.requestPayloadDigest, firstIdempotentCommand.requestPayloadDigest);
  const conflictingIdempotentCommand = await cloudFunction.main({
    action: "CREATE_COMMAND",
    data: Object.assign({}, idempotentCommand, { payload: { count: 2 } }),
  });
  assert.equal(conflictingIdempotentCommand.ok, false);
  assert.match(conflictingIdempotentCommand.error, /IDEMPOTENCY_CONFLICT/);
  const concurrentIdempotentCommands = await Promise.all([
    cloudFunction.main({
      action: "CREATE_COMMAND",
      data: Object.assign({}, idempotentCommand, {
        requestId: "concurrent-command-request",
        payload: { count: 3 },
      }),
    }),
    cloudFunction.main({
      action: "CREATE_COMMAND",
      data: Object.assign({}, idempotentCommand, {
        requestId: "concurrent-command-request",
        payload: { count: 4 },
      }),
    }),
  ]);
  assert.equal(concurrentIdempotentCommands.filter(result => result.status === "pending").length, 1);
  assert.equal(
    concurrentIdempotentCommands.filter(result => /IDEMPOTENCY_CONFLICT/.test(result.error || "")).length,
    1,
  );

  const remoteCabinet = await cloudFunction.main({
    action: "CREATE_COMMAND",
    data: {
      deviceId: "zykh-qsm-001",
      type: "OPEN_CABINET",
      payload: { slot: 8, remote_confirmed: true },
    },
  });
  assert.equal(remoteCabinet.ok, false);
  assert.match(remoteCabinet.error, /unsupported command type/);
  assert.equal(inserted, 1, "remote cabinet commands must never enter the command queue");

  const invalidMedicine = await cloudFunction.main({
    action: "CREATE_COMMAND",
    data: {
      deviceId: "zykh-qsm-001",
      type: "UPSERT_MEDICINE",
      payload: { operation: "patch", slot: 1, patch: { quantity: -1 } },
    },
  });
  assert.equal(invalidMedicine.ok, false);
  assert.match(invalidMedicine.error, /quantity/);
  assert.equal(inserted, 1);

  const conflictingSlotMedicine = await cloudFunction.main({
    action: "CREATE_COMMAND",
    data: {
      deviceId: "zykh-qsm-001",
      type: "UPSERT_MEDICINE",
      payload: {
        operation: "patch",
        hardware_slot: 1,
        patch: { hardwareSlot: 2, name: "不应串仓的药品" },
      },
    },
  });
  assert.equal(conflictingSlotMedicine.ok, false);
  assert.match(conflictingSlotMedicine.error, /conflicting medicine slot/);
  assert.equal(inserted, 1);

  const medicinePatch = {
    operation: "patch",
    hardware_slot: 1,
    patch: {
      name: "演示药品",
      spec: "0.3克×10袋",
      traceCode: "TRACE-001",
      quantity: 0,
      lowStockLine: 2,
      expireDate: "2030-02",
      expiryPrecision: "month",
    },
  };
  const validMedicine = await cloudFunction.main({
    action: "CREATE_COMMAND",
    data: {
      deviceId: "zykh-qsm-001",
      type: "UPSERT_MEDICINE",
      payload: medicinePatch,
    },
  });
  assert.equal(validMedicine.status, "pending");
  assert.deepEqual(insertedRows[1].payload, medicinePatch);
  assert.equal(insertedRows[1].payload.patch.quantity, 0);
  assert.equal(inserted, 2);

  const remoteReviewedMedicine = await cloudFunction.main({
    action: "CREATE_COMMAND",
    data: {
      deviceId: "zykh-qsm-001",
      type: "UPSERT_MEDICINE",
      payload: {
        operation: "patch",
        hardware_slot: 1,
        patch: { safety_review_status: "reviewed", safety_reviewed_by: "远程自称药师" },
      },
    },
  });
  assert.equal(remoteReviewedMedicine.ok, false);
  assert.match(remoteReviewedMedicine.error, /unsupported medicine patch field/);
  assert.equal(inserted, 2);

  const draftSafetyPatch = {
    operation: "patch",
    hardware_slot: 1,
    patch: {
      aliases: ["云端草稿别名"],
      active_ingredients: ["云端草稿成分"],
      structured_contraindications: [
        { concept_code: "ingredient_allergy", display_text: "云端草稿辅料过敏者禁用" },
      ],
      safety_review_status: "draft",
    },
  };
  const draftSafetyMedicine = await cloudFunction.main({
    action: "CREATE_COMMAND",
    data: {
      deviceId: "zykh-qsm-001",
      type: "UPSERT_MEDICINE",
      payload: draftSafetyPatch,
    },
  });
  assert.equal(draftSafetyMedicine.status, "pending");
  assert.deepEqual(insertedRows[2].payload, draftSafetyPatch);
  assert.equal(inserted, 3);

  const medicineSnapshotRow = {
    slot: 1,
    hardwareSlot: 1,
    name: "演示药品",
    spec: "0.3克×10袋",
    traceCode: "TRACE-001",
    quantity: 0,
    lowStockLine: 2,
    expireDate: "2030-02",
    expiryPrecision: "month",
  };
  process.env.DEVICE_SECRET = "server-test-secret";
  delete process.env.DEVICE_SECRETS;
  const batch = await cloudFunction.main({
    action: "UPSERT_SNAPSHOT_BATCH",
    data: {
      deviceId: "zykh-qsm-001",
      deviceSecret: "server-test-secret",
      kind: "medicines",
      rows: [medicineSnapshotRow],
    },
  });
  assert.equal(batch.count, 1);
  const medicines = await cloudFunction.main({
    action: "LIST_MEDICINES",
    data: { deviceId: "zykh-qsm-001", limit: 10 },
  });
  assert.equal(medicines.length, 1);
  for (const field of ["spec", "traceCode", "quantity", "lowStockLine", "expireDate", "expiryPrecision"]) {
    assert.equal(medicines[0][field], medicineSnapshotRow[field], `${field} changed in CloudBase storage`);
  }
  if (originalSharedSecret === undefined) delete process.env.DEVICE_SECRET;
  else process.env.DEVICE_SECRET = originalSharedSecret;
  if (originalDeviceSecrets === undefined) delete process.env.DEVICE_SECRETS;
  else process.env.DEVICE_SECRETS = originalDeviceSecrets;
  console.log("cloud function command security contract: ok");
}

run().catch(error => {
  console.error(error);
  process.exit(1);
});
