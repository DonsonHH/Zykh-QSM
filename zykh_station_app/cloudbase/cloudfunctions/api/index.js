const cloud = require("wx-server-sdk");

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });

const db = cloud.database();
const schemaRevision = "2.3-medicine-sync-contract";

const collections = {
  devices: "devices",
  medicines: "medicines",
  vitals: "vitals",
  records: "records",
  commands: "commands",
  serviceUsers: "service_users",
  plans: "today_plans",
  inquiries: "inquiries",
};

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
]);

const readActions = new Set([
  "GET_DEVICE",
  "LIST_MEDICINES",
  "GET_LATEST_VITALS",
  "LIST_VITALS",
  "LIST_RECORDS",
  "LIST_COMMANDS",
  "LIST_INQUIRIES",
  "GET_SNAPSHOT",
]);

const allowedCommandTypes = new Set([
  "AUDIO_BEEP",
  "AUDIO_SPEAK",
  "READ_VITALS_ALL",
  "AI_CHAT",
  "UPSERT_MEDICINE",
  "UPSERT_SERVICE_USER",
  "UPSERT_TODAY_PLAN",
  "OPEN_CABINET",
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

function safeId(value) {
  return String(value || "unknown").replace(/[^A-Za-z0-9_.-]/g, "-");
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
  ]);
  if (operation === "patch") {
    const unknown = Object.keys(source).filter(key => !allowedPatchFields.has(key));
    if (unknown.length) throw new Error(`unsupported medicine patch field: ${unknown[0]}`);
    if (Object.keys(source).length === 0) throw new Error("medicine patch must include at least one field");
  }

  validateNonNegativeInteger(source, "quantity", "stock");
  validateNonNegativeInteger(source, "lowStockLine", "low_stock_line");
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

function expectedDeviceSecret(deviceId) {
  try {
    const map = JSON.parse((process.env.DEVICE_SECRETS || "{}").trim() || "{}");
    if (Object.prototype.hasOwnProperty.call(map, deviceId)) {
      return String(map[deviceId] || "").trim();
    }
  } catch (error) {
    // Fall through to the shared secret.
  }
  return (process.env.DEVICE_SECRET || "").trim();
}

function validateDevice(data) {
  if (!data || !data.deviceId) return { ok: false, error: "deviceId required" };
  const expected = expectedDeviceSecret(data.deviceId);
  if (expected && data.deviceSecret !== expected) return { ok: false, error: "unauthorized" };
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

async function replaceDeviceRows(collection, deviceId, rows, idForRow) {
  const ids = [];
  for (const row of rows || []) {
    const id = idForRow(row);
    ids.push(id);
    await setDocument(collection, id, Object.assign(cleanData(row), {
      deviceId,
      syncOwner: "zykh_station_app",
      updatedAt: nowText(),
    }));
  }
  const existing = await listAllDeviceRows(collection, deviceId);
  const keep = new Set(ids);
  await Promise.all(existing
    .filter(item => item.syncOwner === "zykh_station_app" && !keep.has(item._id))
    .map(item => db.collection(collection).doc(item._id).remove()));
  return ids.length;
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
  const limit = Math.min(Number(data.limit) || 100, 100);
  const rows = await tryListRows(collections.inquiries, data.deviceId, limit, "updatedAt");
  const commandRows = (await tryListRows(collections.commands, data.deviceId, 100, "updatedAt"))
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
    .slice(0, limit);
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
    counts.serviceUsers = await replaceDeviceRows(collections.serviceUsers, deviceId, snapshot.serviceUsers || [], row => `${deviceId}-user-${safeId(row.id || row.user_id || row.name)}`);
  }
  if (Object.prototype.hasOwnProperty.call(snapshot, "plans")) {
    counts.plans = await replaceDeviceRows(collections.plans, deviceId, snapshot.plans || [], row => `${deviceId}-plan-${safeId(row.id)}`);
  }
  if (Object.prototype.hasOwnProperty.call(snapshot, "inquiries")) {
    counts.inquiries = await replaceDeviceRows(collections.inquiries, deviceId, snapshot.inquiries || [], row => `${deviceId}-inquiry-${safeId(row.inquiry_id || row.session_id || row.id)}`);
  }
  if (Object.prototype.hasOwnProperty.call(snapshot, "vitals")) {
    counts.vitals = await replaceDeviceRows(collections.vitals, deviceId, snapshot.vitals || [], row => `${deviceId}-vitals-${safeId(row.id || row.measured_at || row.createdAt)}`);
  }
  if (Object.prototype.hasOwnProperty.call(snapshot, "records")) {
    counts.records = await replaceDeviceRows(collections.records, deviceId, snapshot.records || [], row => `${deviceId}-record-${safeId(row.id || row.created_at || row.createdAt)}`);
  }
  return { counts, syncedAt: nowText(), schemaVersion: 2 };
}

function snapshotKind(kind, deviceId) {
  const map = {
    medicines: [collections.medicines, row => `${deviceId}-slot-${Number(row.slot || row.hardware_slot || 0)}`],
    serviceUsers: [collections.serviceUsers, row => `${deviceId}-user-${safeId(row.id || row.user_id || row.name)}`],
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
  }
  return { kind: data.kind, ids, count: ids.length };
}

async function finalizeSnapshot(data) {
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
  await db.collection(collections.commands).doc(data.commandId).update({
    data: { status, result: data.result || {}, updatedAt: nowText() },
  });
  if (command.data && command.data.type === "AI_CHAT") {
    try {
      const mirrored = commandToInquiry(Object.assign({}, command.data, {
        _id: data.commandId,
        status,
        result: data.result || {},
        updatedAt: nowText(),
      }));
      await setDocument(collections.inquiries, `${data.deviceId}-inquiry-${safeId(data.commandId)}`, mirrored);
    } catch (error) {
      // Command ACK must remain reliable even if the optional inquiry mirror is not ready.
    }
  }
  return { commandId: data.commandId, status };
}

async function createCommand(data, wxContext, isHttp) {
  if (isHttp) throw new Error("miniprogram function invocation required");
  if (!wxContext.OPENID) throw new Error("miniprogram identity required");
  if (!allowedCommandTypes.has(data.type)) throw new Error("unsupported command type");
  if (data.type === "UPSERT_MEDICINE") validateMedicineCommand(data.payload || {});
  if (data.type === "OPEN_CABINET" && (!data.payload || data.payload.remote_confirmed !== true)) {
    throw new Error("remote cabinet confirmation required");
  }
  const row = {
    deviceId: data.deviceId,
    type: data.type,
    payload: data.payload || {},
    status: "pending",
    source: "miniprogram",
    sourceOpenId: wxContext.OPENID || "",
    createdAt: nowText(),
    updatedAt: nowText(),
  };
  if (data.requestId) {
    const documentId = `${data.deviceId}-request-${safeId(data.requestId)}`;
    try {
      const existing = (await db.collection(collections.commands).doc(documentId).get()).data;
      if (existing) return existing;
    } catch (error) {
      // A missing document is created below.
    }
    await setDocument(collections.commands, documentId, row);
    return Object.assign({ _id: documentId }, row);
  }
  const result = await db.collection(collections.commands).add({ data: row });
  return Object.assign({ _id: result._id }, row);
}

async function handleAction(payload, wxContext, isHttp = false) {
  const action = payload.action;
  const data = payload.data || {};
  if (action === "PING") {
    return { ok: true, time: nowText(), schemaVersion: 2, schemaRevision, collections };
  }
  if (boardActions.has(action)) {
    const error = validateDevice(data);
    if (error) return error;
  } else if (readActions.has(action) || action === "CREATE_COMMAND") {
    const error = validateDeviceId(data);
    if (error) return error;
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
    case "CREATE_COMMAND": return createCommand(data, wxContext, isHttp);
    case "GET_DEVICE": {
      try {
        return (await db.collection(collections.devices).doc(data.deviceId).get()).data || null;
      } catch (error) {
        return null;
      }
    }
    case "LIST_MEDICINES": return listRows(collections.medicines, data.deviceId, data.limit, "slot", "asc");
    case "GET_LATEST_VITALS": return (await listRows(collections.vitals, data.deviceId, 1, "createdAt"))[0] || null;
    case "LIST_VITALS": return listRows(collections.vitals, data.deviceId, data.limit, "createdAt");
    case "LIST_RECORDS": return listRows(collections.records, data.deviceId, data.limit, "createdAt");
    case "LIST_COMMANDS": return listRows(collections.commands, data.deviceId, data.limit, "updatedAt");
    case "LIST_INQUIRIES": return listInquiries(data);
    case "GET_SNAPSHOT": return {
      serviceUsers: await tryListRows(collections.serviceUsers, data.deviceId, 100, "updatedAt"),
      plans: await tryListRows(collections.plans, data.deviceId, 100, "updatedAt"),
      inquiries: await listInquiries(data),
      vitals: await tryListRows(collections.vitals, data.deviceId, 100, "createdAt"),
    };
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
