const cloud = require("wx-server-sdk");
const { createInvocationHandler } = require("./invocation");
const { createSubscribeMessageSender } = require("./subscribeMessageSender");
const { createCaregiverNotificationWorker } = require("./worker");

const TIMER_TRIGGER_NAME = "caregiver-notification-worker-timer";
const DEFAULT_NOTIFICATION_PAGE = "pages/records/index";

function parseTemplateIds(value) {
  try {
    const parsed = JSON.parse(String(value || "{}").trim() || "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed)
        .map(([key, templateId]) => [String(key || "").trim(), String(templateId || "").trim()])
        .filter(([key, templateId]) => key && templateId),
    );
  } catch (error) {
    return {};
  }
}

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();
const sender = createSubscribeMessageSender({
  templateIds: parseTemplateIds(process.env.CAREGIVER_NOTIFICATION_TEMPLATE_IDS),
  sendSubscribeMessage: payload => cloud.openapi.subscribeMessage.send(payload),
});
const worker = createCaregiverNotificationWorker({
  db,
  collections: {
    notifications: "caregiver_notification_outbox",
    events: "medication_safety_events",
    memberships: "device_memberships",
    subscriptions: "caregiver_notification_subscriptions",
    receipts: "caregiver_event_receipts",
  },
  sender,
  notificationPage: String(
    process.env.CAREGIVER_NOTIFICATION_PAGE || DEFAULT_NOTIFICATION_PAGE,
  ).trim(),
  staleAfterMs: Number(process.env.CAREGIVER_NOTIFICATION_STALE_AFTER_MS) || 10 * 60 * 1000,
});
const invoke = createInvocationHandler({
  worker,
  getOpenId: () => {
    const context = cloud.getWXContext();
    return context && context.OPENID;
  },
  controlToken: process.env.CAREGIVER_NOTIFICATION_WORKER_TOKEN || "",
  timerTriggerName: process.env.CAREGIVER_NOTIFICATION_TRIGGER_NAME || TIMER_TRIGGER_NAME,
});

exports.main = (event, context) => invoke(event, context);
