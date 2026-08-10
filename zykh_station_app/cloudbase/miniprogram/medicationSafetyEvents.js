function currentDeviceId() {
  const app = getApp();
  return app.globalData.deviceId || wx.getStorageSync("deviceId") || "zykh-qsm-001";
}

function firstPresent(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return null;
}

function textValue(...values) {
  return String(firstPresent(...values) || "");
}

function normalizedCheckStatus(value) {
  const status = textValue(value).trim().toUpperCase();
  return ["PASSED", "BLOCKED", "CHECK_FAILED"].includes(status)
    ? status
    : "CHECK_FAILED";
}

function normalizedDispenseStatus(value) {
  const status = textValue(value).trim().toUpperCase();
  return ["NOT_STARTED", "BLOCKED", "DISPENSED", "HARDWARE_FAILED", "RESULT_UNKNOWN"].includes(status)
    ? status
    : "NOT_STARTED";
}

async function cloudAction(action, data = {}) {
  const response = await wx.cloud.callFunction({
    name: "api",
    data: {
      action,
      data: Object.assign({ deviceId: currentDeviceId() }, data),
    },
  });
  if (!response || !response.result) throw new Error("云端安全记录返回无效数据");
  if (response.result.ok === false) {
    throw new Error(response.result.error || "云端安全记录请求失败");
  }
  return response.result;
}

function normalizeMedicationSafetyEvent(row = {}) {
  const medicine = row.medicine && typeof row.medicine === "object" ? row.medicine : {};
  const reasonCodes = firstPresent(row.reasonCodes, row.reason_codes);
  return {
    eventId: textValue(row.eventId, row.event_id),
    personId: textValue(row.personId, row.service_user_id, row.serviceUserId),
    personName: textValue(
      row.personName,
      row.person_display_name,
      row.personDisplayName,
      row.service_user_name,
      row.serviceUserName,
      "家庭成员",
    ),
    medicineId: textValue(row.medicineId, row.medicine_id, medicine.id),
    medicineName: textValue(row.medicineName, row.medicine_name, medicine.name, "未命名药品"),
    slot: Number(firstPresent(row.slot, medicine.slot, 0)) || 0,
    checkStatus: normalizedCheckStatus(firstPresent(row.checkStatus, row.check_status)),
    dispenseStatus: normalizedDispenseStatus(firstPresent(row.dispenseStatus, row.dispense_status)),
    summary: textValue(
      row.summary,
      row.caregiverSummary,
      row.caregiver_summary,
      row.reasonSummary,
      row.reason_summary,
    ),
    occurredAt: textValue(row.occurredAt, row.occurred_at),
    read: row.read === true,
    reasonCodes: Array.isArray(reasonCodes) ? reasonCodes.map(value => String(value)) : [],
    profileRevision: Number(firstPresent(row.profileRevision, row.profile_revision, 0)) || 0,
    rulesetVersion: textValue(row.rulesetVersion, row.ruleset_version),
    medicineReviewFingerprint: textValue(
      row.medicineReviewFingerprint,
      row.medicine_review_fingerprint,
    ),
    qsmOperationId: textValue(row.qsmOperationId, row.qsm_operation_id),
    physicalFailureSummary: textValue(
      row.physicalFailureSummary,
      row.physical_failure_summary,
    ),
  };
}

async function getMedicationSafetyCapability() {
  const ping = await cloudAction("PING");
  const version = textValue(ping.capabilities && ping.capabilities.medicationSafetyEvents);
  return {
    supported: version === "v1",
    version,
    schemaRevision: textValue(ping.schemaRevision),
  };
}

async function listMedicationSafetyEvents(options = {}) {
  const data = {};
  for (const field of ["personId", "checkStatus", "unreadOnly", "limit", "cursor"]) {
    if (options[field] !== undefined) data[field] = options[field];
  }
  const result = await cloudAction("LIST_MEDICATION_SAFETY_EVENTS", data);
  return {
    items: Array.isArray(result.items) ? result.items.map(normalizeMedicationSafetyEvent) : [],
    nextCursor: textValue(result.nextCursor, result.next_cursor),
  };
}

async function getMedicationSafetyEvent(eventId) {
  const normalizedEventId = textValue(eventId).trim();
  if (!normalizedEventId) throw new Error("eventId required");
  const result = await cloudAction("GET_MEDICATION_SAFETY_EVENT", { eventId: normalizedEventId });
  return normalizeMedicationSafetyEvent(result.event || result);
}

// This only records the current caregiver's read receipt. It cannot report,
// approve, unblock, dispense, or enqueue a Station command.
async function markMedicationSafetyEventRead(eventId) {
  const normalizedEventId = textValue(eventId).trim();
  if (!normalizedEventId) throw new Error("eventId required");
  return cloudAction("MARK_MEDICATION_SAFETY_EVENT_READ", { eventId: normalizedEventId });
}

module.exports = {
  getMedicationSafetyCapability,
  getMedicationSafetyEvent,
  listMedicationSafetyEvents,
  markMedicationSafetyEventRead,
  normalizeMedicationSafetyEvent,
};
