const cloud = require("wx-server-sdk");
const {
  canonicalPayloadDigest,
  createMedicationSafetyEventModule,
} = require("./medicationSafetyEvents");
const { createMembershipModule } = require("./memberships");
const {
  legacyServiceUserDocumentId,
  serviceUserDocumentId,
  serviceUserIdentity,
} = require("./serviceUserIdentity");

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();
const schemaRevision = "2.8-runtime-persona-consistency";
const capabilities = Object.freeze({
  medicationSafetyEvents: "v1",
  caregiverMembership: "v1",
  inquiryDetail: "v1",
  snapshotBatch: "v2",
  devicePairing: "v1",
  devicePairingIssue: "v1",
  caregiverNotificationOutbox: "v1",
  caregiverNotificationWorker: "v1",
  explicitInventoryState: "v1",
  personaLifecycle: "v1",
  serviceUserPersonaTombstones: "v1",
  vitalsAttribution: "v1",
});

const collections = {
  devices: "devices",
  medicines: "medicines",
  vitals: "vitals",
  records: "records",
  commands: "commands",
  serviceUsers: "service_users",
  plans: "today_plans",
  inquiries: "inquiries",
  medicationSafetyEvents: "medication_safety_events",
  caregiverEventReceipts: "caregiver_event_receipts",
  caregiverNotificationOutbox: "caregiver_notification_outbox",
  caregiverNotificationSubscriptions: "caregiver_notification_subscriptions",
  deviceMemberships: "device_memberships",
  devicePairingCodes: "device_pairing_codes",
};

const memberships = createMembershipModule({
  db,
  collections,
  nowText,
  nowEpochMs: () => Date.now(),
});
const medicationSafetyEvents = createMedicationSafetyEventModule({
  db,
  collections,
  memberships,
  nowText,
  safeId,
});

const boardActions = new Set([
  "REPORT_DEVICE",
  "UPLOAD_MEDICINES",
  "UPLOAD_VITALS",
  "UPLOAD_RECORD",
  "UPLOAD_SNAPSHOT",
  "UPSERT_SNAPSHOT_BATCH",
  "FINALIZE_SNAPSHOT",
  "PULL_COMMANDS",
  "ACK_COMMAND",
  "ISSUE_DEVICE_PAIRING_CODE",
]);

const readActions = new Set([
  "GET_DEVICE",
  "LIST_MEDICINES",
  "GET_LATEST_VITALS",
  "LIST_VITALS",
  "LIST_RECORDS",
  "LIST_COMMANDS",
  "LIST_INQUIRIES",
  "GET_INQUIRY_DETAIL",
  "GET_SNAPSHOT",
  "LIST_MEDICATION_SAFETY_EVENTS",
  "GET_MEDICATION_SAFETY_EVENT",
  "MARK_MEDICATION_SAFETY_EVENT_READ",
]);

const readActionPermissions = Object.freeze({
  GET_LATEST_VITALS: "READ_VITALS",
  GET_INQUIRY_DETAIL: "READ_INQUIRY",
  LIST_MEDICINES: "READ_MEDICINE",
  LIST_COMMANDS: "CREATE_COMMAND",
  LIST_INQUIRIES: "READ_INQUIRY",
  LIST_RECORDS: "READ_RECORD",
  LIST_VITALS: "READ_VITALS",
});

const allowedCommandTypes = new Set([
  "AUDIO_BEEP",
  "AUDIO_SPEAK",
  "READ_VITALS_ALL",
  "AI_CHAT",
  "UPSERT_MEDICINE",
  "UPSERT_SERVICE_USER",
  "UPSERT_TODAY_PLAN",
]);

function nowText() {
  const date = new Date(Date.now() + 8 * 60 * 60 * 1000);
  const pad = value => String(value).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`;
}

function firstPresent(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return null;
}

function cleanData(value) {
  const result = Object.assign({}, value || {});
  delete result._id;
  delete result._openid;
  delete result.deviceSecret;
  return result;
}

function compactTextList(...values) {
  for (const value of values) {
    if (Array.isArray(value)) {
      return value.map(item => String(item || "").trim()).filter(Boolean).slice(0, 3);
    }
    if (typeof value === "string" && value.trim()) return [value.trim()];
  }
  return [];
}

function compactInquiryCare(row = {}) {
  const extracted = row.extracted_information || row.extractedInformation || {};
  const assessment = row.final_assessment
    || row.finalAssessment
    || extracted.final_assessment
    || extracted.finalAssessment
    || {};
  return {
    summary: firstPresent(
      row.reasoning_summary,
      row.reasoningSummary,
      row.summary,
      assessment.summary,
      "",
    ),
    next_steps: compactTextList(
      row.next_steps,
      row.nextSteps,
      assessment.next_steps,
      assessment.nextSteps,
    ),
    seek_care_if: compactTextList(
      row.seek_care_if,
      row.seekCareIf,
      assessment.seek_care_if,
      assessment.seekCareIf,
    ),
  };
}

function inquiryMessageCount(row = {}, sourceMessages = []) {
  const declared = Number(firstPresent(row.messageCount, row.message_count, ""));
  const declaredCount = Number.isInteger(declared) && declared >= 0 ? declared : 0;
  return Math.max(sourceMessages.length, declaredCount);
}

function compactInquiryMessage(message = {}, index = 0) {
  return {
    id: firstPresent(message.id, message._id, `msg-${index}`),
    role: firstPresent(message.role, message.sender, ""),
    content: firstPresent(message.content, message.text, message.message, ""),
    source: firstPresent(message.source, message.origin, ""),
    created_at: firstPresent(message.created_at, message.createdAt, message.time, ""),
  };
}

function compactInquiryForClient(row = {}, options = {}) {
  const includeMessages = options.includeMessages === true;
  const sourceMessages = Array.isArray(row.messages) ? row.messages : [];
  const care = compactInquiryCare(row);
  const messages = includeMessages
    ? sourceMessages.map(compactInquiryMessage).filter(item => item.content).slice(-80)
    : [];
  return {
    _id: firstPresent(row._id, ""),
    deviceId: firstPresent(row.deviceId, row.device_id, ""),
    inquiry_id: firstPresent(row.inquiry_id, row.session_id, row._id, ""),
    session_id: firstPresent(row.session_id, row.inquiry_session_id, ""),
    sourceCommandId: firstPresent(row.sourceCommandId, row.source_command_id, ""),
    target_user_id: firstPresent(
      row.target_user_id,
      row.service_user_id,
      row.user_id,
      row.person_id,
      row.patient_id,
      "",
    ),
    service_user_id: firstPresent(row.service_user_id, row.target_user_id, ""),
    user_id: firstPresent(row.user_id, ""),
    person_id: firstPresent(row.person_id, ""),
    patient_id: firstPresent(row.patient_id, ""),
    service_user_name_snapshot: firstPresent(
      row.service_user_name_snapshot,
      row.service_user_name,
      row.target_user_name,
      "",
    ),
    display_name: firstPresent(
      row.service_user_name_snapshot,
      row.target_user_name,
      row.service_user_name,
      row.patient_name,
      row.user_name,
      row.person_name,
      "",
    ),
    target_user_name: firstPresent(
      row.target_user_name,
      row.service_user_name_snapshot,
      row.patient_name,
      row.user_name,
      "家庭成员",
    ),
    persona_generation: firstPresent(row.persona_generation, row.personaGeneration, ""),
    identity_kind: firstPresent(row.identity_kind, row.identityKind, ""),
    title: firstPresent(row.title, row.topic, row.symptoms_summary, "AI 问询"),
    topic: firstPresent(row.topic, row.title, row.symptoms_summary, "AI 问询"),
    symptoms_summary: firstPresent(
      row.symptoms_summary,
      row.symptomsText,
      row.symptoms_text,
      row.title,
      "",
    ),
    reasoning_summary: care.summary,
    reply: firstPresent(row.reply, row.ai_message, row.message, ""),
    ai_message: firstPresent(row.ai_message, row.reply, ""),
    risk_label: firstPresent(row.risk_label, row.riskLevel, row.risk_level, ""),
    risk_level: firstPresent(row.risk_level, row.riskLevel, ""),
    final_assessment: care,
    next_steps: care.next_steps,
    seek_care_if: care.seek_care_if,
    status: firstPresent(row.status, row.action_status, "done"),
    stage: firstPresent(row.stage, row.inquiry_stage, ""),
    next_action: firstPresent(row.next_action, row.nextAction, ""),
    messageCount: inquiryMessageCount(row, sourceMessages),
    syncedMessageCount: Number(firstPresent(
      row.syncedMessageCount,
      row.synced_message_count,
      sourceMessages.length,
      0,
    )) || 0,
    conversationTruncated: row.conversationTruncated === true || row.conversation_truncated === true,
    messages,
    created_at: firstPresent(row.created_at, row.createdAt, ""),
    updated_at: firstPresent(row.updated_at, row.updatedAt, row.created_at, row.createdAt, ""),
    createdAt: firstPresent(row.created_at, row.createdAt, ""),
    updatedAt: firstPresent(row.updated_at, row.created_at, row.updatedAt, row.createdAt, ""),
    syncOwner: firstPresent(row.syncOwner, ""),
  };
}

function safeId(value) {
  return String(value || "unknown").replace(/[^A-Za-z0-9_.-]/g, "-");
}

async function migrateExactLegacyServiceUserDocument(deviceId, row, canonicalId) {
  const legacyId = legacyServiceUserDocumentId(deviceId, row);
  if (legacyId === canonicalId) return;
  let legacy;
  try {
    legacy = (await db.collection(collections.serviceUsers).doc(legacyId).get()).data || null;
  } catch (error) {
    return;
  }
  const { personId, generation } = serviceUserIdentity(row);
  const legacyPersonId = String(firstPresent(legacy.id, legacy.user_id, legacy.userId) || "").trim();
  const legacyGeneration = String(firstPresent(legacy.persona_generation, legacy.personaGeneration) || "").trim();
  if (
    String(legacy.deviceId || "").trim() === deviceId
    && legacyPersonId === personId
    && (!legacyGeneration || legacyGeneration === generation)
  ) {
    await db.collection(collections.serviceUsers).doc(legacyId).remove();
  }
}

function normalizeVitals(vitals = {}) {
  return Object.assign({}, vitals, {
    heartRate: firstPresent(vitals.heartRate, vitals.heart_rate, vitals.heart_rate_bpm),
    spo2: firstPresent(vitals.spo2, vitals.spo2_percent),
    bodyTemp: firstPresent(vitals.bodyTemp, vitals.body_temp_c, vitals.target_temp_c, vitals.temperature),
    quality: firstPresent(vitals.quality, vitals.signal_quality, vitals.status, "unknown"),
    createdAt: firstPresent(vitals.createdAt, vitals.created_at, vitals.measured_at, vitals.time),
  });
}

function presentValue(source, ...names) {
  for (const name of names) {
    if (Object.prototype.hasOwnProperty.call(source || {}, name)) {
      return { present: true, value: source[name] };
    }
  }
  return { present: false, value: undefined };
}

function validateNonNegativeInteger(source, ...names) {
  const field = presentValue(source, ...names);
  if (!field.present) return;
  const value = Number(field.value);
  if (!Number.isInteger(value) || value < 0) throw new Error(`${names[0]} must be a non-negative integer`);
}

function validateMedicineCommand(payload = {}) {
  const operation = String(payload.operation || "upsert").toLowerCase();
  if (!["upsert", "patch"].includes(operation)) throw new Error("unsupported medicine operation");
  if (operation === "patch" && (!payload.patch || typeof payload.patch !== "object" || Array.isArray(payload.patch))) {
    throw new Error("medicine patch required");
  }
  const source = operation === "patch" ? payload.patch : payload;
  const slotValues = [
    payload.hardware_slot,
    payload.hardwareSlot,
    payload.slot,
    source.hardware_slot,
    source.hardwareSlot,
    source.slot,
  ].filter(value => value !== undefined && value !== null && value !== "");
  if (new Set(slotValues.map(value => String(value).trim())).size > 1) {
    throw new Error("conflicting medicine slot fields");
  }
  const slotField = firstPresent(
    ...slotValues,
  );
  const slot = Number(slotField);
  if (!Number.isInteger(slot) || slot < 1 || slot > 23) throw new Error("medicine slot must be between 1 and 23");

  const allowedPatchFields = new Set([
    "name", "manufacturer", "barcode", "code", "category", "spec", "trace_code", "traceCode",
    "stock", "quantity", "low_stock_line", "lowStockLine", "unit", "expire_date", "expireDate",
    "expiryPrecision", "hardware_slot", "hardwareSlot", "slot",
    "inventoryState", "inventory_state",
    "aliases", "active_ingredients", "structured_contraindications", "safety_review_status",
  ]);
  if (operation === "patch") {
    const unknown = Object.keys(source).filter(key => !allowedPatchFields.has(key));
    if (unknown.length) throw new Error(`unsupported medicine patch field: ${unknown[0]}`);
    if (Object.keys(source).length === 0) throw new Error("medicine patch must include at least one field");
  }

  validateNonNegativeInteger(source, "quantity", "stock");
  if (source !== payload) validateNonNegativeInteger(payload, "quantity", "stock");
  validateNonNegativeInteger(source, "lowStockLine", "low_stock_line");
  const inventoryStates = [];
  const quantities = [];
  for (const candidate of source === payload ? [source] : [payload, source]) {
    for (const fieldName of ["inventoryState", "inventory_state"]) {
      if (!Object.prototype.hasOwnProperty.call(candidate, fieldName)) continue;
      const value = String(candidate[fieldName] || "").trim().toUpperCase();
      if (value) inventoryStates.push(value);
    }
    for (const fieldName of ["quantity", "stock"]) {
      if (!Object.prototype.hasOwnProperty.call(candidate, fieldName)) continue;
      const value = Number(candidate[fieldName]);
      if (!Number.isInteger(value) || value < 0) throw new Error("quantity must be a non-negative integer");
      quantities.push(value);
    }
  }
  const distinctInventoryStates = Array.from(new Set(inventoryStates));
  if (distinctInventoryStates.length > 1) throw new Error("conflicting medicine inventory state fields");
  const inventoryState = distinctInventoryStates[0] || "";
  if (inventoryState && !["STOCKED", "DEPLETED", "UNKNOWN"].includes(inventoryState)) {
    throw new Error("unsupported medicine inventory state");
  }
  const distinctQuantities = Array.from(new Set(quantities));
  if (distinctQuantities.length > 1) throw new Error("conflicting medicine quantity fields");
  const quantity = distinctQuantities.length ? distinctQuantities[0] : null;
  if (inventoryState === "STOCKED" && quantity !== null && quantity <= 0) {
    throw new Error("STOCKED medicine quantity must be positive");
  }
  if (inventoryState === "DEPLETED" && quantity !== null && quantity !== 0) {
    throw new Error("DEPLETED medicine quantity must be zero");
  }
  for (const fieldName of ["aliases", "active_ingredients"]) {
    const field = presentValue(source, fieldName);
    if (!field.present) continue;
    if (!Array.isArray(field.value) || field.value.length > 12
        || field.value.some(value => !String(value || "").trim())) {
      throw new Error(`${fieldName} must be a non-empty text array with at most 12 items`);
    }
  }
  const structured = presentValue(source, "structured_contraindications");
  if (structured.present && (
    !Array.isArray(structured.value)
    || structured.value.length > 12
    || structured.value.some(item => !item || typeof item !== "object" || Array.isArray(item)
      || !String(item.concept_code || "").trim()
      || !String(item.display_text || "").trim())
  )) {
    throw new Error("structured_contraindications must contain concept_code and display_text");
  }
  const safetyReviewStatus = presentValue(source, "safety_review_status");
  if (safetyReviewStatus.present && String(safetyReviewStatus.value || "").trim().toLowerCase() !== "draft") {
    throw new Error("remote safety_review_status must remain draft");
  }
  const name = presentValue(source, "name");
  if (name.present && !String(name.value || "").trim()) throw new Error("medicine name must not be empty");
  if (operation === "upsert" && !String(name.value || "").trim()) throw new Error("medicine name required");

  const camelExpiry = presentValue(source, "expireDate");
  const snakeExpiry = presentValue(source, "expire_date");
  if (camelExpiry.present && snakeExpiry.present && String(camelExpiry.value) !== String(snakeExpiry.value)) {
    throw new Error("conflicting medicine expiry fields");
  }
  const expiry = String(camelExpiry.present ? camelExpiry.value : snakeExpiry.present ? snakeExpiry.value : "").trim();
  if (expiry && !/^\d{4}-\d{2}(?:-\d{2})?$/.test(expiry)) throw new Error("invalid medicine expiry");
  const precision = presentValue(source, "expiryPrecision");
  if (precision.present) {
    const expected = /^\d{4}-\d{2}-\d{2}$/.test(expiry) ? "day" : /^\d{4}-\d{2}$/.test(expiry) ? "month" : "unknown";
    if (!expiry || String(precision.value) !== expected) throw new Error("medicine expiryPrecision does not match expireDate");
  }
}

function configuredDeviceSecrets() {
  try {
    const map = JSON.parse((process.env.DEVICE_SECRETS || "{}").trim() || "{}");
    return map && typeof map === "object" && !Array.isArray(map) ? map : {};
  } catch (error) {
    return {};
  }
}

function expectedPerDeviceSecret(deviceId) {
  const map = configuredDeviceSecrets();
  return Object.prototype.hasOwnProperty.call(map, deviceId)
    ? String(map[deviceId] || "").trim()
    : "";
}

function expectedDeviceSecret(deviceId) {
  const perDevice = expectedPerDeviceSecret(deviceId);
  if (perDevice) return perDevice;
  return (process.env.DEVICE_SECRET || "").trim();
}

function validateDevice(data) {
  if (!data || !data.deviceId) return { ok: false, error: "deviceId required" };
  const expected = expectedDeviceSecret(data.deviceId);
  if (!expected) return { ok: false, error: "device secret is not configured" };
  if (data.deviceSecret !== expected) return { ok: false, error: "unauthorized" };
  return null;
}

function validatePairingIssuer(data) {
  if (!data || !data.deviceId) return { ok: false, error: "deviceId required" };
  const expected = expectedPerDeviceSecret(data.deviceId);
  if (!expected) return { ok: false, error: "per-device secret is not configured" };
  if (data.deviceSecret !== expected) return { ok: false, error: "unauthorized" };
  return null;
}

function validateSafetyEventReporter(data) {
  if (!data || !data.deviceId) return { ok: false, error: "deviceId required" };
  const expected = expectedDeviceSecret(data.deviceId);
  if (!expected) return { ok: false, error: "device secret is not configured" };
  if (data.deviceSecret !== expected) return { ok: false, error: "unauthorized" };
  return null;
}

function validateDeviceId(data) {
  return data && data.deviceId ? null : { ok: false, error: "deviceId required" };
}

function parseEvent(event = {}) {
  if (event.action) return { payload: event, isHttp: false };
  let body = event.body;
  if (event.isBase64Encoded && typeof body === "string") {
    body = Buffer.from(body, "base64").toString("utf8");
  }
  if (typeof body === "string") {
    try {
      body = body ? JSON.parse(body) : {};
    } catch (error) {
      body = {};
    }
  }
  if (body && body.action) return { payload: body, isHttp: true };
  if (event.queryStringParameters && event.queryStringParameters.action) {
    return {
      payload: {
        action: event.queryStringParameters.action,
        data: event.queryStringParameters,
      },
      isHttp: true,
    };
  }
  return { payload: event, isHttp: Boolean(event.httpMethod || event.headers || event.requestContext) };
}

function httpResult(result) {
  return {
    statusCode: 200,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Allow-Methods": "POST,OPTIONS",
    },
    body: JSON.stringify(result),
  };
}

async function setDocument(collection, id, data) {
  await db.collection(collection).doc(id).set({ data: cleanData(data) });
}

async function listAllDeviceRows(collection, deviceId, maximum = 2000) {
  const rows = [];
  for (let offset = 0; offset < maximum; offset += 100) {
    const result = await db.collection(collection)
      .where({ deviceId })
      .orderBy("_id", "asc")
      .skip(offset)
      .limit(100)
      .get();
    const batch = result.data || [];
    rows.push(...batch);
    if (batch.length < 100) break;
  }
  return rows;
}

async function replaceDeviceRows(collection, deviceId, rows, idForRow, afterSet = null) {
  const ids = [];
  for (const row of rows || []) {
    const id = idForRow(row);
    ids.push(id);
    await setDocument(collection, id, Object.assign(cleanData(row), {
      deviceId,
      syncOwner: "zykh_station_app",
      updatedAt: nowText(),
    }));
    if (afterSet) await afterSet(row, id);
  }
  const existing = await listAllDeviceRows(collection, deviceId);
  const keep = new Set(ids);
  await Promise.all(existing
    .filter(item => item.syncOwner === "zykh_station_app" && !keep.has(item._id))
    .map(item => db.collection(collection).doc(item._id).remove()));
  return ids.length;
}

async function upsertDeviceRows(collection, deviceId, rows, idForRow) {
  for (const row of rows || []) {
    const id = idForRow(row);
    await setDocument(collection, id, Object.assign(cleanData(row), {
      deviceId,
      syncOwner: "zykh_station_app",
      updatedAt: nowText(),
    }));
  }
  return (rows || []).length;
}

async function listRows(collection, deviceId, limit = 100, order = "updatedAt", direction = "desc") {
  let query = db.collection(collection).where({ deviceId });
  if (order) query = query.orderBy(order, direction);
  const result = await query.limit(Math.min(Number(limit) || 20, 100)).get();
  return result.data || [];
}

async function tryListRows(collection, deviceId, limit = 100, order = "updatedAt", direction = "desc") {
  try {
    return await listRows(collection, deviceId, limit, order, direction);
  } catch (error) {
    return [];
  }
}

function commandToInquiry(command = {}) {
  const payload = command.payload || {};
  const result = command.result || {};
  const commandId = command._id || command.id || command.commandId || "";
  const question = firstPresent(payload.question, payload.message, payload.prompt, result.question, "");
  const reply = firstPresent(
    result.reply,
    result.answer,
    result.ai_message,
    result.message,
    result.content,
    result.text,
    result.summary,
    result.error,
    "",
  );
  const createdAt = firstPresent(command.createdAt, command.created_at, command.updatedAt, nowText());
  const updatedAt = firstPresent(command.updatedAt, command.updated_at, createdAt);
  const messages = [];
  if (question) {
    messages.push({
      id: `${commandId || "ai"}-question`,
      role: "user",
      content: question,
      source: "miniprogram",
      created_at: createdAt,
    });
  }
  if (reply) {
    messages.push({
      id: `${commandId || "ai"}-reply`,
      role: command.status === "failed" ? "system" : "assistant",
      content: reply,
      source: "board",
      created_at: updatedAt,
    });
  }
  return {
    deviceId: command.deviceId,
    inquiry_id: commandId,
    sourceCommandId: commandId,
    target_user_id: firstPresent(payload.target_user_id, payload.user_id, ""),
    target_user_name: firstPresent(payload.target_user_name, payload.user_name, payload.patient_name, "家庭成员"),
    persona_generation: firstPresent(
      command.persona_generation,
      command.personaGeneration,
      payload.persona_generation,
      payload.personaGeneration,
      "",
    ),
    title: question || "AI 问诊",
    topic: question || "AI 问诊",
    symptoms_summary: question || "AI 问诊",
    reasoning_summary: firstPresent(result.reasoning_summary, result.summary, ""),
    reply,
    ai_message: reply,
    risk_label: firstPresent(result.risk_label, result.riskLevel, result.risk_level, ""),
    risk_level: firstPresent(result.risk_level, result.riskLevel, ""),
    status: command.status || "done",
    messages,
    created_at: createdAt,
    updated_at: updatedAt,
    createdAt,
    updatedAt,
    syncOwner: "ai_command",
  };
}

function summaryInquiryRows(device = {}) {
  const summary = device.syncSummary || {};
  return (summary.recentInquiries || []).map(row => Object.assign({}, row, {
    deviceId: device.deviceId || device._id,
    updatedAt: firstPresent(row.updatedAt, row.updated_at, row.createdAt, row.created_at, row.created_at),
    syncOwner: "device_summary",
  }));
}

function inquiryRowKey(row = {}) {
  return String(firstPresent(row.sourceCommandId, row.inquiry_id, row.session_id, row._id, `${row.createdAt || row.created_at}-${row.title || row.symptoms_summary}`));
}

function inquiryTime(row = {}) {
  const text = String(firstPresent(row.updatedAt, row.updated_at, row.createdAt, row.created_at, "")).replace(/-/g, "/");
  const time = Date.parse(text);
  return Number.isFinite(time) ? time : 0;
}

async function listInquiries(data) {
  const limit = Math.min(Math.max(Number(data.limit) || 100, 1), 2000);
  const rows = await listAllDeviceRows(collections.inquiries, data.deviceId);
  const commandRows = (await listAllDeviceRows(collections.commands, data.deviceId))
    .filter(command => command.type === "AI_CHAT")
    .map(commandToInquiry);
  let summaryRows = [];
  try {
    const device = (await db.collection(collections.devices).doc(data.deviceId).get()).data || {};
    summaryRows = summaryInquiryRows(Object.assign({ deviceId: data.deviceId }, device));
  } catch (error) {
    summaryRows = [];
  }
  const map = new Map();
  rows.concat(commandRows, summaryRows).forEach(row => {
    const key = inquiryRowKey(row);
    const current = map.get(key);
    const currentMessages = Array.isArray(current && current.messages) ? current.messages.length : 0;
    const nextMessages = Array.isArray(row.messages) ? row.messages.length : 0;
    if (!current || nextMessages >= currentMessages || inquiryTime(row) >= inquiryTime(current)) {
      map.set(key, row);
    }
  });
  return Array.from(map.values())
    .sort((a, b) => inquiryTime(b) - inquiryTime(a))
    .slice(0, limit)
    .map(row => compactInquiryForClient(row, { includeMessages: false }));
}

function membershipScopes(membership = {}) {
  const value = membership.service_user_scopes || membership.serviceUserScopes;
  return Array.isArray(value)
    ? value.map(item => String(item || "").trim()).filter(Boolean)
    : [];
}

function membershipGenerations(membership = {}) {
  const value = membership.service_user_generations || membership.serviceUserGenerations;
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value)
    .map(([key, generation]) => [String(key || "").trim(), String(generation || "").trim()])
    .filter(([key, generation]) => key && generation));
}

function membershipHasPermission(membership = {}, permission) {
  return Array.isArray(membership.permissions)
    && membership.permissions.includes(permission);
}

function rowIsArchived(row = {}) {
  return row.archived === true
    || Number(row.archived) === 1
    || String(row.archived || "").toLowerCase() === "true";
}

function rowPersonId(row = {}, kind = "") {
  if (kind === "serviceUsers") {
    return String(firstPresent(row.id, row.user_id, row.userId, row.service_user_id, row.serviceUserId) || "").trim();
  }
  const payload = row.payload && typeof row.payload === "object" ? row.payload : {};
  return String(firstPresent(
    row.service_user_id,
    row.serviceUserId,
    row.user_id,
    row.userId,
    row.target_user_id,
    row.targetUserId,
    row.person_id,
    row.personId,
    payload.service_user_id,
    payload.serviceUserId,
    payload.user_id,
    payload.userId,
    payload.target_user_id,
    payload.targetUserId,
    payload.person_id,
    payload.personId,
  ) || "").trim();
}

function rowsVisibleToMembership(rows, membership, kind = "") {
  const publicRows = kind === "serviceUsers"
    ? (rows || []).filter(row => !rowIsArchived(row))
    : (rows || []);
  const scopes = membershipScopes(membership);
  if (!scopes.length) return publicRows;
  const allowed = new Set(scopes);
  const generations = membershipGenerations(membership);
  return publicRows.filter(row => {
    const personId = rowPersonId(row, kind);
    if (!allowed.has(personId)) return false;
    const expectedGeneration = generations[personId];
    if (Object.keys(generations).length && !expectedGeneration) return false;
    if (!expectedGeneration) return true;
    const payload = row.payload && typeof row.payload === "object" ? row.payload : {};
    const actualGeneration = String(firstPresent(
      row.persona_generation,
      row.personaGeneration,
      payload.persona_generation,
      payload.personaGeneration,
    ) || "").trim();
    if (!actualGeneration) return false;
    return actualGeneration === expectedGeneration;
  });
}

function deviceVisibleToMembership(device, membership) {
  if (!device) return device;
  const source = device.syncSummary && typeof device.syncSummary === "object"
    ? device.syncSummary
    : {};
  const syncSummary = { counts: {} };
  if (membershipHasPermission(membership, "READ_PROFILE")) {
    syncSummary.serviceUsers = rowsVisibleToMembership(
      Array.isArray(source.serviceUsers) ? source.serviceUsers : [],
      membership,
      "serviceUsers",
    );
    syncSummary.counts.serviceUsers = syncSummary.serviceUsers.length;
    if (Object.prototype.hasOwnProperty.call(source, "serviceUsersSnapshotComplete")) {
      syncSummary.serviceUsersSnapshotComplete = source.serviceUsersSnapshotComplete === true;
    }
  }
  if (membershipHasPermission(membership, "READ_PLAN")) {
    syncSummary.plans = rowsVisibleToMembership(
      Array.isArray(source.plans) ? source.plans : [],
      membership,
      "plans",
    );
    syncSummary.counts.plans = syncSummary.plans.length;
  }
  if (membershipHasPermission(membership, "READ_INQUIRY")) {
    syncSummary.recentInquiries = rowsVisibleToMembership(
      Array.isArray(source.recentInquiries) ? source.recentInquiries : [],
      membership,
      "inquiries",
    ).map(row => compactInquiryForClient(row, { includeMessages: false }));
    syncSummary.counts.inquiries = syncSummary.recentInquiries.length;
  }
  return Object.assign(cleanData(device), { syncSummary });
}

function commandPersonId(type, payload = {}) {
  if (type === "UPSERT_SERVICE_USER") {
    return String(firstPresent(
      payload.id,
      payload.service_user_id,
      payload.serviceUserId,
      payload.user_id,
      payload.userId,
    ) || "").trim();
  }
  return rowPersonId({ payload }, "commands");
}

function requestedLimit(data, fallback = 20) {
  return Math.min(Math.max(Number(data.limit) || fallback, 1), 100);
}

async function scopedRows(collection, data, membership, order, direction = "desc", kind = "") {
  const rows = await listAllDeviceRows(collection, data.deviceId);
  const multiplier = direction === "asc" ? 1 : -1;
  rows.sort((left, right) => {
    const byOrder = String(left[order] || "").localeCompare(String(right[order] || ""));
    if (byOrder) return byOrder * multiplier;
    return String(left._id || "").localeCompare(String(right._id || "")) * multiplier;
  });
  return rowsVisibleToMembership(rows, membership, kind).slice(0, requestedLimit(data));
}

async function snapshotVisibleToMembership(data, membership) {
  const snapshot = {};
  if (membershipHasPermission(membership, "READ_PROFILE")) {
    snapshot.serviceUsers = rowsVisibleToMembership(
      await listAllDeviceRows(collections.serviceUsers, data.deviceId),
      membership,
      "serviceUsers",
    );
    // listAllDeviceRows completes every database page before returning, so this
    // marker is only published when the visible profile snapshot is complete.
    snapshot.serviceUsersSnapshotComplete = true;
  }
  if (membershipHasPermission(membership, "READ_PLAN")) {
    snapshot.plans = rowsVisibleToMembership(
      await listAllDeviceRows(collections.plans, data.deviceId),
      membership,
      "plans",
    );
  }
  if (membershipHasPermission(membership, "READ_INQUIRY")) {
    snapshot.inquiries = rowsVisibleToMembership(
      await listInquiries(Object.assign({}, data, { limit: 2000 })),
      membership,
      "inquiries",
    );
  }
  if (membershipHasPermission(membership, "READ_VITALS")) {
    snapshot.vitals = rowsVisibleToMembership(
      await listAllDeviceRows(collections.vitals, data.deviceId),
      membership,
      "vitals",
    );
  }
  return snapshot;
}

async function getInquiryDetail(data, membership) {
  const inquiryId = String(data.inquiryId || data.inquiry_id || data.sessionId || data.session_id || "").trim();
  if (!inquiryId) throw new Error("inquiryId required");

  const storedRows = await listAllDeviceRows(collections.inquiries, data.deviceId);
  const commandRows = (await listAllDeviceRows(collections.commands, data.deviceId))
    .filter(command => command.type === "AI_CHAT")
    .map(commandToInquiry);
  let summaryRows = [];
  try {
    const device = (await db.collection(collections.devices).doc(data.deviceId).get()).data || {};
    summaryRows = summaryInquiryRows(Object.assign({ deviceId: data.deviceId }, device));
  } catch (error) {
    summaryRows = [];
  }
  const visible = rowsVisibleToMembership(
    storedRows.concat(commandRows, summaryRows),
    membership,
    "inquiries",
  );
  const row = visible.find(item => [
    item._id,
    item.inquiry_id,
    item.session_id,
    item.sourceCommandId,
  ].some(value => String(value || "") === inquiryId));
  if (!row) throw new Error("NOT_FOUND");
  return compactInquiryForClient(row, { includeMessages: true });
}

async function reportDevice(data) {
  try {
    const current = (await db.collection(collections.devices).doc(data.deviceId).get()).data || {};
    if (Number(current.schemaVersion || 0) >= 2 && Number(data.schemaVersion || 0) < 2) {
      return current;
    }
  } catch (error) {
    // The first heartbeat creates the document below.
  }
  const patch = Object.assign(cleanData(data), {
    online: true,
    lastSeenAt: nowText(),
    updatedAt: nowText(),
  });
  await setDocument(collections.devices, data.deviceId, patch);
  return patch;
}

async function uploadMedicines(data) {
  const count = await replaceDeviceRows(
    collections.medicines,
    data.deviceId,
    data.medicines || [],
    row => `${data.deviceId}-slot-${Number(row.slot || row.hardware_slot || 0)}`,
  );
  return { count };
}

async function uploadVitals(data) {
  if (!data.vitals) throw new Error("vitals required");
  const row = Object.assign(normalizeVitals(data.vitals), {
    deviceId: data.deviceId,
    createdAt: firstPresent(data.vitals.createdAt, data.vitals.created_at, data.vitals.measured_at, nowText()),
  });
  const id = `${data.deviceId}-vitals-${safeId(data.vitals.id || data.vitals.recordId || row.createdAt)}`;
  await setDocument(collections.vitals, id, row);
  return Object.assign({ _id: id }, row);
}

async function uploadRecord(data) {
  if (!data.record) throw new Error("record required");
  const row = Object.assign(cleanData(data.record), {
    deviceId: data.deviceId,
    createdAt: data.record.createdAt || data.record.created_at || nowText(),
  });
  const id = `${data.deviceId}-record-${safeId(data.record.id || data.record.recordId || row.createdAt)}`;
  await setDocument(collections.records, id, row);
  return Object.assign({ _id: id }, row);
}

async function uploadSnapshot(data) {
  const deviceId = data.deviceId;
  const snapshot = data.snapshot || {};
  const counts = {};
  if (Object.prototype.hasOwnProperty.call(snapshot, "medicines")) {
    counts.medicines = await replaceDeviceRows(collections.medicines, deviceId, snapshot.medicines || [], row => `${deviceId}-slot-${Number(row.slot || row.hardware_slot || 0)}`);
  }
  if (Object.prototype.hasOwnProperty.call(snapshot, "serviceUsers")) {
    counts.serviceUsers = await replaceDeviceRows(
      collections.serviceUsers,
      deviceId,
      snapshot.serviceUsers || [],
      row => serviceUserDocumentId(deviceId, row),
      (row, id) => migrateExactLegacyServiceUserDocument(deviceId, row, id),
    );
  }
  if (Object.prototype.hasOwnProperty.call(snapshot, "plans")) {
    counts.plans = await replaceDeviceRows(collections.plans, deviceId, snapshot.plans || [], row => `${deviceId}-plan-${safeId(row.id)}`);
  }
  if (Object.prototype.hasOwnProperty.call(snapshot, "inquiries")) {
    counts.inquiries = await upsertDeviceRows(collections.inquiries, deviceId, snapshot.inquiries || [], row => `${deviceId}-inquiry-${safeId(row.inquiry_id || row.session_id || row.id)}`);
  }
  if (Object.prototype.hasOwnProperty.call(snapshot, "vitals")) {
    counts.vitals = await upsertDeviceRows(collections.vitals, deviceId, snapshot.vitals || [], row => `${deviceId}-vitals-${safeId(row.id || row.measured_at || row.createdAt)}`);
  }
  if (Object.prototype.hasOwnProperty.call(snapshot, "records")) {
    counts.records = await replaceDeviceRows(collections.records, deviceId, snapshot.records || [], row => `${deviceId}-record-${safeId(row.id || row.created_at || row.createdAt)}`);
  }
  return { counts, syncedAt: nowText(), schemaVersion: 2 };
}

function snapshotKind(kind, deviceId) {
  const map = {
    medicines: [collections.medicines, row => `${deviceId}-slot-${Number(row.slot || row.hardware_slot || 0)}`],
    serviceUsers: [collections.serviceUsers, row => serviceUserDocumentId(deviceId, row)],
    plans: [collections.plans, row => `${deviceId}-plan-${safeId(row.id)}`],
    inquiries: [collections.inquiries, row => `${deviceId}-inquiry-${safeId(row.inquiry_id || row.session_id || row.id)}`],
    vitals: [collections.vitals, row => `${deviceId}-vitals-${safeId(row.id || row.measured_at || row.createdAt)}`],
    records: [collections.records, row => `${deviceId}-record-${safeId(row.id || row.created_at || row.createdAt)}`],
  };
  if (!map[kind]) throw new Error("unsupported snapshot kind");
  return map[kind];
}

async function upsertSnapshotBatch(data) {
  const [collection, idForRow] = snapshotKind(data.kind, data.deviceId);
  const ids = [];
  for (const row of data.rows || []) {
    const id = idForRow(row);
    ids.push(id);
    const normalized = data.kind === "vitals" ? normalizeVitals(cleanData(row)) : cleanData(row);
    if (data.kind === "vitals") {
      normalized.createdAt = firstPresent(
        row.measured_at,
        row.measuredAt,
        row.createdAt,
        row.created_at,
        normalized.createdAt,
        nowText(),
      );
    }
    await setDocument(collection, id, Object.assign(normalized, {
      deviceId: data.deviceId,
      syncOwner: "zykh_station_app",
      updatedAt: nowText(),
    }));
    if (data.kind === "serviceUsers") {
      await migrateExactLegacyServiceUserDocument(data.deviceId, row, id);
    }
  }
  return { kind: data.kind, ids, count: ids.length };
}

async function finalizeSnapshot(data) {
  if (data.kind === "inquiries" || data.kind === "vitals") {
    snapshotKind(data.kind, data.deviceId);
    return { kind: data.kind, removed: 0, appendOnly: true };
  }
  const [collection] = snapshotKind(data.kind, data.deviceId);
  const keep = new Set(data.ids || []);
  const existing = await listAllDeviceRows(collection, data.deviceId);
  const stale = existing.filter(item => item.syncOwner === "zykh_station_app" && !keep.has(item._id));
  await Promise.all(stale.map(item => db.collection(collection).doc(item._id).remove()));
  if (data.kind === "records") await cleanupLegacyRecords(data.deviceId);
  return { kind: data.kind, removed: stale.length };
}

async function cleanupLegacyRecords(deviceId) {
  const legacyTypes = new Set(["SERVICE_USER", "TODAY_PLAN", "INQUIRY"]);
  const records = await listAllDeviceRows(collections.records, deviceId);
  const legacy = records.filter(item => legacyTypes.has(item.type) && !item.syncOwner);
  await Promise.all(legacy.map(item => db.collection(collections.records).doc(item._id).remove()));
  return legacy.length;
}

async function pullCommands(data) {
  try {
    const current = (await db.collection(collections.devices).doc(data.deviceId).get()).data || {};
    if (Number(current.schemaVersion || 0) >= 2 && Number(data.agentVersion || 0) < 2) {
      return [];
    }
  } catch (error) {
    // Missing device state is handled by the normal query below.
  }

  const running = await db.collection(collections.commands)
    .where({ deviceId: data.deviceId, status: "running" })
    .limit(20)
    .get();
  const staleBefore = Date.now() - 120 * 1000;
  await Promise.all((running.data || []).map(command => {
    const text = String(command.pulledAt || command.updatedAt || "").replace(/-/g, "/");
    const timestamp = Date.parse(text);
    if (!Number.isFinite(timestamp) || timestamp >= staleBefore) return Promise.resolve();
    return db.collection(collections.commands).doc(command._id).update({
      data: { status: "pending", recoveryReason: "stale-running", updatedAt: nowText() },
    });
  }));

  const result = await db.collection(collections.commands)
    .where({ deviceId: data.deviceId, status: "pending" })
    .orderBy("createdAt", "asc")
    .limit(Math.min(Number(data.limit) || 10, 20))
    .get();
  const pulledAt = nowText();
  await Promise.all((result.data || []).map(command => db.collection(collections.commands).doc(command._id).update({
    data: { status: "running", pulledAt, updatedAt: pulledAt },
  })));
  return (result.data || []).map(command => Object.assign({}, command, { status: "running", pulledAt, updatedAt: pulledAt }));
}

async function ackCommand(data) {
  if (!data.commandId) throw new Error("commandId required");
  const command = await db.collection(collections.commands).doc(data.commandId).get();
  if (command.data && command.data.deviceId !== data.deviceId) throw new Error("unauthorized command");
  const status = data.status || "done";
  const result = data.result && typeof data.result === "object" ? data.result : {};
  await db.collection(collections.commands).doc(data.commandId).update({
    data: { status, result, updatedAt: nowText() },
  });
  if (command.data && command.data.type === "AI_CHAT") {
    try {
      const mirrored = commandToInquiry(Object.assign({}, command.data, {
        _id: data.commandId,
        status,
        result,
        updatedAt: nowText(),
      }));
      await setDocument(collections.inquiries, `${data.deviceId}-inquiry-${safeId(data.commandId)}`, mirrored);
    } catch (error) {
      // Command ACK must remain reliable even if the optional inquiry mirror is not ready.
    }
  }
  if (command.data && command.data.type === "READ_VITALS_ALL" && status === "done") {
    try {
      await mirrorVitalsCommand(data.deviceId, data.commandId, command.data, result);
    } catch (error) {
      // Command ACK must remain reliable even if the optional vitals mirror is not ready.
    }
  }
  return { commandId: data.commandId, status };
}

function commandVitalsPayload(result = {}) {
  if (result.vitals && typeof result.vitals === "object") return result.vitals;
  if (result.data && typeof result.data === "object") return result.data;
  if (result.result && typeof result.result === "object") return result.result;
  return result;
}

function hasVitalsSignal(row = {}) {
  return [
    row.heartRate,
    row.heart_rate,
    row.heart_rate_bpm,
    row.spo2,
    row.spo2_percent,
    row.bodyTemp,
    row.body_temp_c,
    row.target_temp_c,
    row.temperature,
    row.body_temperature,
    row.status,
    row.quality,
  ].some(value => value !== undefined && value !== null && value !== "");
}

async function mirrorVitalsCommand(deviceId, commandId, command, result) {
  const measured = commandVitalsPayload(result);
  const authoritative = Object.assign({}, result, measured);
  const payload = command && command.payload && typeof command.payload === "object"
    ? command.payload
    : {};
  if (!hasVitalsSignal(authoritative)) return null;
  const normalized = normalizeVitals(authoritative);
  const createdAt = firstPresent(
    authoritative.measured_at,
    authoritative.measuredAt,
    authoritative.createdAt,
    authoritative.created_at,
    normalized.createdAt,
    command.updatedAt,
    command.createdAt,
    nowText(),
  );
  const serviceUserId = firstPresent(
    authoritative.service_user_id,
    authoritative.serviceUserId,
    authoritative.person_id,
    authoritative.personId,
    payload.service_user_id,
    payload.serviceUserId,
    payload.person_id,
    payload.personId,
    "",
  );
  const serviceUserName = firstPresent(
    authoritative.service_user_name_snapshot,
    authoritative.serviceUserNameSnapshot,
    authoritative.service_user_name,
    authoritative.serviceUserName,
    authoritative.person_name,
    authoritative.personName,
    payload.service_user_name_snapshot,
    payload.serviceUserNameSnapshot,
    payload.service_user_name,
    payload.serviceUserName,
    payload.person_name,
    payload.personName,
    "",
  );
  const row = Object.assign({}, normalized, {
    deviceId,
    device_id: deviceId,
    createdAt,
    measured_at: firstPresent(authoritative.measured_at, authoritative.measuredAt, createdAt),
    updatedAt: nowText(),
    sourceCommandId: commandId,
    source: firstPresent(authoritative.source, result.source, "READ_VITALS_ALL"),
    service_user_id: serviceUserId,
    service_user_name_snapshot: serviceUserName,
    persona_generation: firstPresent(
      authoritative.persona_generation,
      authoritative.personaGeneration,
      payload.persona_generation,
      payload.personaGeneration,
      "",
    ),
    inquiry_session_id: firstPresent(
      authoritative.inquiry_session_id,
      authoritative.inquirySessionId,
      payload.inquiry_session_id,
      payload.inquirySessionId,
      "",
    ),
    attribution_source: firstPresent(
      authoritative.attribution_source,
      authoritative.attributionSource,
      payload.attribution_source,
      payload.attributionSource,
      serviceUserId ? "REMOTE_COMMAND" : "STANDALONE",
    ),
    target_user_id: serviceUserId,
    target_user_name: serviceUserName,
    syncOwner: "command_ack",
  });
  const id = `${deviceId}-vitals-command-${safeId(commandId)}`;
  await setDocument(collections.vitals, id, row);
  return Object.assign({ _id: id }, row);
}

async function createCommand(data, wxContext, isHttp) {
  if (isHttp) throw new Error("miniprogram function invocation required");
  if (!wxContext.OPENID) throw new Error("miniprogram identity required");
  const personScopedTypes = new Set([
    "AI_CHAT",
    "READ_VITALS_ALL",
    "UPSERT_SERVICE_USER",
    "UPSERT_TODAY_PLAN",
  ]);
  const commandPayload = Object.assign({}, data.payload || {});
  const personId = commandPersonId(data.type, commandPayload);
  const isVitalsCommand = data.type === "READ_VITALS_ALL";
  const attributionSource = String(firstPresent(
    commandPayload.attribution_source,
    commandPayload.attributionSource,
    "",
  ) || "").trim().toUpperCase();
  const isStandaloneVitals = isVitalsCommand && attributionSource === "STANDALONE";
  if (isVitalsCommand && !personId && !isStandaloneVitals) throw new Error("INVALID_ARGUMENT");
  if (isVitalsCommand && personId && isStandaloneVitals) throw new Error("INVALID_ARGUMENT");
  if (isVitalsCommand && personId && !attributionSource) {
    commandPayload.attribution_source = "REMOTE_COMMAND";
  }
  const membership = await memberships.requireCommandAccess({
    openId: wxContext.OPENID,
    deviceId: data.deviceId,
    personId,
  });
  if (isStandaloneVitals && membershipScopes(membership).length) throw new Error("NOT_FOUND");
  if (personScopedTypes.has(data.type) && !personId && !isStandaloneVitals) throw new Error("NOT_FOUND");
  if (!allowedCommandTypes.has(data.type)) throw new Error("unsupported command type");
  const personaGeneration = String(
    membership.current_persona_generation || "",
  ).trim();
  if (personScopedTypes.has(data.type) && personId && personaGeneration) {
    commandPayload.persona_generation = personaGeneration;
  }
  if (data.type === "UPSERT_MEDICINE") validateMedicineCommand(commandPayload);
  const row = {
    deviceId: data.deviceId,
    type: data.type,
    payload: commandPayload,
    persona_generation: personaGeneration,
    status: "pending",
    source: "miniprogram",
    sourceOpenId: wxContext.OPENID || "",
    createdAt: nowText(),
    updatedAt: nowText(),
  };
  if (data.requestId) {
    const documentId = `${data.deviceId}-request-${safeId(data.requestId)}`;
    const requestPayloadDigest = canonicalPayloadDigest({
      deviceId: data.deviceId,
      type: data.type,
      payload: commandPayload,
    });
    row.requestPayloadDigest = requestPayloadDigest;
    if (typeof db.runTransaction !== "function") {
      throw new Error("database transaction is unavailable");
    }
    return db.runTransaction(async transaction => {
      const document = transaction.collection(collections.commands).doc(documentId);
      try {
        const existing = (await document.get()).data;
        if (existing) {
          const existingDigest = String(existing.requestPayloadDigest || "");
          if (!existingDigest || existingDigest !== requestPayloadDigest) {
            throw new Error("IDEMPOTENCY_CONFLICT");
          }
          return existing;
        }
      } catch (error) {
        if (error && error.message === "IDEMPOTENCY_CONFLICT") throw error;
        // A missing document is created below while the transaction holds the key.
      }
      await document.set({ data: cleanData(row) });
      return Object.assign({ _id: documentId }, row);
    });
  }
  const result = await db.collection(collections.commands).add({ data: row });
  return Object.assign({ _id: result._id }, row);
}

function requireMiniprogramIdentity(wxContext, isHttp) {
  if (isHttp) throw new Error("miniprogram function invocation required");
  const openId = String((wxContext && wxContext.OPENID) || "").trim();
  if (!openId) throw new Error("miniprogram identity required");
  return openId;
}

async function handleAction(payload, wxContext, isHttp = false) {
  const action = payload.action;
  const data = payload.data || {};
  const safetyReadActions = new Set([
    "LIST_MEDICATION_SAFETY_EVENTS",
    "GET_MEDICATION_SAFETY_EVENT",
    "MARK_MEDICATION_SAFETY_EVENT_READ",
  ]);
  let readMembership = null;
  if (action === "PING") {
    return { ok: true, time: nowText(), schemaVersion: 2, schemaRevision, capabilities, collections };
  }
  if (action === "REPORT_MEDICATION_SAFETY_EVENT") {
    const error = validateSafetyEventReporter(data);
    if (error) return error;
  } else if (action === "ISSUE_DEVICE_PAIRING_CODE") {
    const error = validatePairingIssuer(data);
    if (error) return error;
  } else if (boardActions.has(action)) {
    const error = validateDevice(data);
    if (error) return error;
  } else if (readActions.has(action) || action === "CREATE_COMMAND") {
    const error = validateDeviceId(data);
    if (error) return error;
    if (readActions.has(action) && !safetyReadActions.has(action)) {
      const membershipInput = {
        openId: wxContext.OPENID,
        deviceId: data.deviceId,
      };
      readMembership = readActionPermissions[action]
        ? await memberships.requirePermission(membershipInput, readActionPermissions[action])
        : await memberships.requireMembership(membershipInput);
    }
  }

  switch (action) {
    case "REPORT_DEVICE": return reportDevice(data);
    case "UPLOAD_MEDICINES": return uploadMedicines(data);
    case "UPLOAD_VITALS": return uploadVitals(data);
    case "UPLOAD_RECORD": return uploadRecord(data);
    case "UPLOAD_SNAPSHOT": return uploadSnapshot(data);
    case "UPSERT_SNAPSHOT_BATCH": return upsertSnapshotBatch(data);
    case "FINALIZE_SNAPSHOT": return finalizeSnapshot(data);
    case "PULL_COMMANDS": return pullCommands(data);
    case "ACK_COMMAND": return ackCommand(data);
    case "ISSUE_DEVICE_PAIRING_CODE": return memberships.issuePairingCode(data);
    case "REPORT_MEDICATION_SAFETY_EVENT": return medicationSafetyEvents.report(data);
    case "LIST_MEDICATION_SAFETY_EVENTS": return medicationSafetyEvents.list(data, wxContext);
    case "GET_MEDICATION_SAFETY_EVENT": return medicationSafetyEvents.get(data, wxContext);
    case "MARK_MEDICATION_SAFETY_EVENT_READ": return medicationSafetyEvents.markRead(data, wxContext);
    case "GET_MY_DEVICES": return memberships.listMyDevices({
      openId: requireMiniprogramIdentity(wxContext, isHttp),
    });
    case "REDEEM_DEVICE_PAIRING_CODE": return memberships.redeemPairingCode({
      openId: requireMiniprogramIdentity(wxContext, isHttp),
      pairingCode: data.pairingCode,
    });
    case "CREATE_COMMAND": return createCommand(data, wxContext, isHttp);
    case "GET_DEVICE": {
      try {
        const device = (await db.collection(collections.devices).doc(data.deviceId).get()).data || null;
        return deviceVisibleToMembership(device, readMembership);
      } catch (error) {
        return null;
      }
    }
    case "LIST_MEDICINES": return listRows(collections.medicines, data.deviceId, data.limit, "slot", "asc");
    case "GET_LATEST_VITALS": return (
      await scopedRows(collections.vitals, Object.assign({}, data, { limit: 1 }), readMembership, "createdAt", "desc", "vitals")
    )[0] || null;
    case "LIST_VITALS": return scopedRows(collections.vitals, data, readMembership, "createdAt", "desc", "vitals");
    case "LIST_RECORDS": return scopedRows(collections.records, data, readMembership, "createdAt", "desc", "records");
    case "LIST_COMMANDS": return scopedRows(collections.commands, data, readMembership, "updatedAt", "desc", "commands");
    case "LIST_INQUIRIES": return rowsVisibleToMembership(
      await listInquiries(Object.assign({}, data, { limit: 2000 })),
      readMembership,
      "inquiries",
    ).slice(0, requestedLimit(data, 100));
    case "GET_INQUIRY_DETAIL": return getInquiryDetail(data, readMembership);
    case "GET_SNAPSHOT": return snapshotVisibleToMembership(data, readMembership);
    default: throw new Error(`unknown action: ${action}`);
  }
}

exports.main = async event => {
  const parsed = parseEvent(event);
  if (parsed.isHttp && event.httpMethod === "OPTIONS") return httpResult({ ok: true });
  try {
    const result = await handleAction(parsed.payload, cloud.getWXContext(), parsed.isHttp);
    return parsed.isHttp ? httpResult(result) : result;
  } catch (error) {
    const result = { ok: false, error: error && error.message ? error.message : String(error) };
    return parsed.isHttp ? httpResult(result) : result;
  }
};
