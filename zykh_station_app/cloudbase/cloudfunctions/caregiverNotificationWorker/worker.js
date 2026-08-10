const crypto = require("node:crypto");

const FIXED_NOTIFICATION_CONTENT = Object.freeze({
  summary: "家庭药箱新增一条取药核查记录",
  instruction: "请打开小程序查看",
});

const MAX_BATCH_SIZE = 50;

function text(value) {
  return String(value || "").trim();
}

function textList(value) {
  return Array.isArray(value)
    ? value.map(item => text(item)).filter(Boolean)
    : [];
}

function field(row, ...names) {
  for (const name of names) {
    if (row && row[name] !== undefined && row[name] !== null && row[name] !== "") {
      return row[name];
    }
  }
  return "";
}

function withoutDocumentId(row) {
  const copy = Object.assign({}, row);
  delete copy._id;
  return copy;
}

function databaseFailure(value) {
  const code = value && (value.errCode ?? value.code);
  const message = String((value && (value.errMsg || value.message)) || "");
  return (
    (code !== undefined
      && code !== null
      && code !== 0
      && code !== "0"
      && String(code).toUpperCase() !== "OK")
    || /:fail\b/i.test(message)
  );
}

function documentNotFound(value) {
  const code = String((value && (value.errCode ?? value.code)) || "").toUpperCase();
  const message = String((value && (value.errMsg || value.message)) || value || "");
  return (
    code === "DATABASE_DOCUMENT_NOT_EXIST"
    || code === "DOCUMENT_NOT_EXIST"
    || /document(?:\s+with\s+_id\s+\S+)?\s+(?:does\s+)?not\s+exist|document\s+not\s+found|文档不存在/i.test(message)
  );
}

function storeUnavailable() {
  return new Error("NOTIFICATION_STORE_UNAVAILABLE");
}

function requireDatabaseSuccess(result) {
  if (databaseFailure(result)) throw storeUnavailable();
  return result;
}

async function databaseCall(operation) {
  try {
    return requireDatabaseSuccess(await operation());
  } catch (error) {
    if (error && error.message === "NOTIFICATION_STORE_UNAVAILABLE") throw error;
    throw storeUnavailable();
  }
}

async function documentOrNull(database, collectionName, documentId) {
  try {
    const result = await database.collection(collectionName).doc(documentId).get();
    if (documentNotFound(result)) return null;
    requireDatabaseSuccess(result);
    return result && result.data ? result.data : null;
  } catch (error) {
    if (documentNotFound(error)) return null;
    throw storeUnavailable();
  }
}

async function findEvent(database, collectionName, eventId, deviceId) {
  return documentOrNull(
    database,
    collectionName,
    `${safeId(deviceId)}-${safeId(eventId)}`,
  );
}

function normalizeBatchSize(value) {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) return 10;
  return Math.min(parsed, MAX_BATCH_SIZE);
}

function eventPersonId(event) {
  return text(field(event, "service_user_id", "serviceUserId", "personId"));
}

function eventDeviceId(event) {
  return text(field(event, "device_id", "deviceId"));
}

function subscriptionDocumentId(openId, templateKey) {
  const digest = crypto.createHash("sha256")
    .update(`${text(openId)}\u0000${text(templateKey)}`, "utf8")
    .digest("hex");
  return `notification-subscription-${digest}`;
}

function safeId(value) {
  return String(value || "unknown").replace(/[^A-Za-z0-9_.-]/g, "-");
}

function receiptDocumentId(deviceId, eventId, openId) {
  return `${safeId(deviceId)}-${safeId(eventId)}-${safeId(openId)}`;
}

function validationFailureCode({ notification, event, membership, subscription, receipt }) {
  if (!event) return "EVENT_NOT_AVAILABLE";
  const eventId = text(field(event, "event_id", "eventId", "_id"));
  const notificationEventId = text(field(notification, "eventId", "event_id"));
  const deviceId = text(field(notification, "deviceId", "device_id"));
  const membershipId = text(field(notification, "membershipId", "membership_id"));
  const recipientOpenId = text(field(notification, "recipientOpenId", "recipient_openid"));
  if (!notificationEventId || eventId !== notificationEventId) return "EVENT_NOT_AVAILABLE";
  if (!deviceId || eventDeviceId(event) !== deviceId) return "EVENT_NOT_AVAILABLE";
  if (!membership) return "AUTHORIZATION_REVOKED";
  if (text(field(membership, "membershipId", "membership_id", "_id")) !== membershipId) return "AUTHORIZATION_REVOKED";
  if (text(field(membership, "openid")) !== recipientOpenId) return "AUTHORIZATION_REVOKED";
  if (text(field(membership, "deviceId", "device_id")) !== deviceId) return "AUTHORIZATION_REVOKED";
  if (text(field(membership, "status")).toUpperCase() !== "ACTIVE") return "AUTHORIZATION_REVOKED";
  if (!textList(membership.permissions).includes("READ_SAFETY")) return "AUTHORIZATION_REVOKED";
  const scopes = textList(field(membership, "service_user_scopes", "serviceUserScopes"));
  const personId = eventPersonId(event);
  if (!personId || (scopes.length && !scopes.includes(personId))) return "AUTHORIZATION_REVOKED";
  if (!receipt) return "RECEIPT_NOT_AVAILABLE";
  if (
    text(field(receipt, "eventId", "event_id")) !== notificationEventId
    || text(field(receipt, "deviceId", "device_id")) !== deviceId
    || text(field(receipt, "openid")) !== recipientOpenId
  ) return "RECEIPT_NOT_AVAILABLE";
  if (text(field(receipt, "state")).toUpperCase() === "READ") return "ALREADY_READ";
  const templateKey = text(field(notification, "templateKey", "template_key"));
  if (
    !subscription
    || text(field(subscription, "openid")) !== recipientOpenId
    || text(field(subscription, "templateKey", "template_key")) !== templateKey
    || text(field(subscription, "status")).toUpperCase() !== "AUTHORIZED"
  ) return "SUBSCRIPTION_NOT_AUTHORIZED";
  return "";
}

function createCaregiverNotificationWorker({
  db,
  collections,
  sender,
  now = () => new Date(),
  createClaimToken = () => crypto.randomUUID(),
  notificationPage = "pages/records/index",
  staleAfterMs = 10 * 60 * 1000,
}) {
  if (!db || typeof db.runTransaction !== "function") throw new Error("transactional database required");
  if (!sender || typeof sender.send !== "function") throw new Error("notification sender required");

  const names = Object.assign({
    notifications: "caregiver_notification_outbox",
    events: "medication_safety_events",
    memberships: "device_memberships",
    subscriptions: "caregiver_notification_subscriptions",
    receipts: "caregiver_event_receipts",
  }, collections || {});

  function nowText() {
    const value = now();
    if (!(value instanceof Date) || !Number.isFinite(value.getTime())) throw new Error("valid clock required");
    return value.toISOString();
  }

  function currentTimeMs() {
    const value = now();
    if (!(value instanceof Date) || !Number.isFinite(value.getTime())) throw new Error("valid clock required");
    return value.getTime();
  }

  async function updateReceiptNotification(
    database,
    notification,
    notificationState,
    notificationAttempts,
    timestamp,
  ) {
    const deviceId = text(field(notification, "deviceId", "device_id"));
    const eventId = text(field(notification, "eventId", "event_id"));
    const recipientOpenId = text(field(notification, "recipientOpenId", "recipient_openid"));
    const documentId = receiptDocumentId(deviceId, eventId, recipientOpenId);
    const receipt = await documentOrNull(database, names.receipts, documentId);
    if (!receipt) return;
    await databaseCall(() => database.collection(names.receipts).doc(documentId).set({
      data: Object.assign(withoutDocumentId(receipt), {
        notificationState,
        notificationAttempts: Math.max(0, Number(notificationAttempts) || 0),
        updatedAt: timestamp,
      }),
    }));
  }

  async function convergeStale(documentId) {
    return db.runTransaction(async transaction => {
      const current = await documentOrNull(transaction, names.notifications, documentId);
      if (!current || text(current.state).toUpperCase() !== "SENDING") return false;
      const leaseTime = Date.parse(text(field(current, "claimedAt", "updatedAt")));
      const stale = !Number.isFinite(leaseTime)
        || currentTimeMs() - leaseTime >= Math.max(1, Number(staleAfterMs) || 1);
      if (!stale) return false;
      const timestamp = nowText();
      await databaseCall(() => transaction.collection(names.notifications).doc(documentId).set({
        data: Object.assign(withoutDocumentId(current), {
          state: "RESULT_UNKNOWN",
          failureCode: "DELIVERY_RESULT_UNKNOWN",
          resultUnknownAt: timestamp,
          updatedAt: timestamp,
        }),
      }));
      await updateReceiptNotification(
        transaction,
        current,
        "RESULT_UNKNOWN",
        current.attempts,
        timestamp,
      );
      return true;
    });
  }

  async function claim(documentId) {
    return db.runTransaction(async transaction => {
      const notification = await documentOrNull(transaction, names.notifications, documentId);
      if (!notification || text(notification.state).toUpperCase() !== "PENDING") return null;

      const eventId = text(field(notification, "eventId", "event_id"));
      const deviceId = text(field(notification, "deviceId", "device_id"));
      const membershipId = text(field(notification, "membershipId", "membership_id"));
      const event = await findEvent(transaction, names.events, eventId, deviceId);
      const membership = await documentOrNull(transaction, names.memberships, membershipId);
      const recipientOpenId = text(field(notification, "recipientOpenId", "recipient_openid"));
      const templateKey = text(field(notification, "templateKey", "template_key"));
      const subscription = await documentOrNull(
        transaction,
        names.subscriptions,
        subscriptionDocumentId(recipientOpenId, templateKey),
      );
      const receipt = await documentOrNull(
        transaction,
        names.receipts,
        receiptDocumentId(deviceId, eventId, recipientOpenId),
      );
      const failureCode = validationFailureCode({
        notification,
        event,
        membership,
        subscription,
        receipt,
      });
      if (failureCode) {
        const timestamp = nowText();
        await databaseCall(() => transaction.collection(names.notifications).doc(documentId).set({
          data: Object.assign(withoutDocumentId(notification), {
            state: "FAILED",
            failureCode,
            failedAt: timestamp,
            updatedAt: timestamp,
          }),
        }));
        await updateReceiptNotification(
          transaction,
          notification,
          "FAILED",
          notification.attempts,
          timestamp,
        );
        return { failed: true };
      }

      const timestamp = nowText();
      const claimToken = text(createClaimToken());
      if (!claimToken) throw new Error("claim token required");
      const claimed = Object.assign(withoutDocumentId(notification), {
        state: "SENDING",
        attempts: (Number(notification.attempts) || 0) + 1,
        claimToken,
        claimedAt: timestamp,
        updatedAt: timestamp,
      });
      await databaseCall(() => (
        transaction.collection(names.notifications).doc(documentId).set({ data: claimed })
      ));
      return { documentId, notification: claimed, claimToken };
    });
  }

  function safeDeliveryCode(value, fallback) {
    const code = text(value).toUpperCase();
    return /^[A-Z0-9_:-]{1,80}$/.test(code) ? code : fallback;
  }

  async function finalize(claimed, state, code) {
    return db.runTransaction(async transaction => {
      const current = await documentOrNull(transaction, names.notifications, claimed.documentId);
      if (
        !current
        || text(current.state).toUpperCase() !== "SENDING"
        || text(current.claimToken) !== claimed.claimToken
      ) return false;
      const timestamp = nowText();
      let terminalFields;
      if (state === "SENT") {
        terminalFields = { sentAt: timestamp, deliveryCode: safeDeliveryCode(code, "OK") };
      } else if (state === "FAILED") {
        terminalFields = {
          failedAt: timestamp,
          failureCode: safeDeliveryCode(code, "PROVIDER_REJECTED"),
        };
      } else {
        terminalFields = {
          resultUnknownAt: timestamp,
          failureCode: "DELIVERY_RESULT_UNKNOWN",
        };
      }
      await databaseCall(() => (
        transaction.collection(names.notifications).doc(claimed.documentId).set({
        data: Object.assign(withoutDocumentId(current), {
          state,
          ...terminalFields,
          updatedAt: timestamp,
        }),
        })
      ));
      await updateReceiptNotification(
        transaction,
        current,
        state,
        current.attempts,
        timestamp,
      );
      return true;
    });
  }

  async function runOnce({ batchSize = 10 } = {}) {
    const limit = normalizeBatchSize(batchSize);
    const staleResult = await databaseCall(() => (
      db.collection(names.notifications)
        .where({ state: "SENDING" })
        .orderBy("claimedAt", "asc")
        .limit(limit)
        .get()
    ));
    let staleConverged = 0;
    for (const candidate of staleResult.data || []) {
      const documentId = text(candidate._id || candidate.notificationId);
      if (documentId && await convergeStale(documentId)) staleConverged += 1;
    }
    const result = await databaseCall(() => (
      db.collection(names.notifications)
        .where({ state: "PENDING" })
        .orderBy("createdAt", "asc")
        .limit(limit)
        .get()
    ));
    const summary = {
      ok: true,
      claimed: 0,
      sent: 0,
      failed: 0,
      resultUnknown: staleConverged,
      staleConverged,
    };
    for (const candidate of result.data || []) {
      const documentId = text(candidate._id || candidate.notificationId);
      if (!documentId) continue;
      const claimed = await claim(documentId);
      if (!claimed) continue;
      if (claimed.failed) {
        summary.failed += 1;
        continue;
      }
      summary.claimed += 1;
      let response;
      try {
        response = await sender.send({
          recipientOpenId: text(claimed.notification.recipientOpenId),
          templateKey: text(claimed.notification.templateKey),
          page: text(notificationPage),
          content: FIXED_NOTIFICATION_CONTENT,
        });
      } catch (error) {
        response = { outcome: "UNKNOWN" };
      }
      if (text(response && response.outcome).toUpperCase() === "SENT") {
        if (await finalize(claimed, "SENT", response && response.code)) summary.sent += 1;
      } else if (text(response && response.outcome).toUpperCase() === "REJECTED") {
        if (await finalize(claimed, "FAILED", response && response.code)) summary.failed += 1;
      } else if (await finalize(claimed, "RESULT_UNKNOWN", "DELIVERY_RESULT_UNKNOWN")) {
        summary.resultUnknown += 1;
      }
    }
    return summary;
  }

  return Object.freeze({ runOnce });
}

module.exports = {
  FIXED_NOTIFICATION_CONTENT,
  createCaregiverNotificationWorker,
};
