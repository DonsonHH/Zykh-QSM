const assert = require("node:assert/strict");
const path = require("node:path");

global.getApp = () => ({ globalData: { deviceId: "zykh-qsm-001" } });

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
    aliases: ["云端草稿别名"],
    active_ingredients: ["云端草稿成分"],
    structured_contraindications: [
      { concept_code: "ingredient_allergy", display_text: "云端草稿辅料过敏者禁用" },
    ],
    safety_review_status: "draft",
  },
};

async function testCommandCompatibility() {
  let writes = 0;
  global.wx = {
    getStorageSync: () => "",
    cloud: {
      callFunction: async () => { throw new Error("unknown action: CREATE_COMMAND"); },
      database: () => ({
        collection: () => ({
          add: async ({ data }) => {
            writes += 1;
            assert.equal(data.status, "pending");
            return { _id: "legacy-command" };
          },
          doc: () => ({
            get: async () => { throw new Error("missing"); },
            set: async () => { writes += 1; },
          }),
        }),
      }),
    },
  };

  const commands = require(path.resolve(__dirname, "remoteCommands.js"));
  assert.equal(
    Object.prototype.hasOwnProperty.call(commands, "requestCabinetOpen"),
    false,
    "the embedded helper must not expose remote cabinet opening",
  );
  await assert.rejects(
    commands.createCommand("OPEN_CABINET", { slot: 8, remote_confirmed: true }),
    /远程开柜已禁用/,
  );
  assert.equal(writes, 0, "remote cabinet requests must not fall back to direct database writes");

  await assert.rejects(
    commands.createCommand("AUDIO_BEEP", {}),
    /云端版本过旧.*升级后重试/,
  );
  assert.equal(writes, 0, "an old cloud function must not trigger a raw collection write");

  wx.cloud.callFunction = async () => ({ result: { _id: "v2-command", status: "pending" } });
  const v2 = await commands.createCommand("AUDIO_BEEP", {});
  assert.equal(v2._id, "v2-command");
  assert.equal(writes, 0);

  let submitted = null;
  wx.cloud.callFunction = async ({ data }) => {
    submitted = data;
    return { result: { _id: "medicine-command", status: "pending", payload: data.data.payload } };
  };
  const medicineCommand = await commands.createCommand("UPSERT_MEDICINE", medicinePatch);
  assert.deepEqual(submitted.data.payload, medicinePatch);
  assert.equal(medicineCommand.payload.patch.quantity, 0);
  assert.equal(medicineCommand.payload.patch.safety_review_status, "draft");

  for (const message of [
    "request timeout",
    "permission denied",
    "unsupported command type",
    "unknown action: LIST_MEDICINES",
  ]) {
    wx.cloud.callFunction = async () => { throw new Error(message); };
    await assert.rejects(commands.createCommand("AUDIO_BEEP", {}), new RegExp(message));
    assert.equal(writes, 0, `${message} must not fall back to a direct database write`);
  }

  wx.cloud.callFunction = async () => ({ result: { ok: false, error: "unknown action: CREATE_COMMAND" } });
  await assert.rejects(
    commands.createCommand("AUDIO_BEEP", {}),
    /云端版本过旧.*升级后重试/,
  );
  assert.equal(writes, 0);

  wx.cloud.callFunction = async () => ({ result: { ok: false, error: "medicine payload validation failed" } });
  await assert.rejects(commands.createCommand("UPSERT_MEDICINE", {}), /validation failed/);
  assert.equal(writes, 0);
}

async function testRealtimeSubscription() {
  let directDatabaseAccesses = 0;
  wx.cloud.callFunction = async ({ data }) => {
    const action = data.action;
    if (action === "GET_SNAPSHOT") throw new Error("v1");
    if (action === "PING") return { result: { ok: true } };
    if (action === "GET_DEVICE") {
      return {
        result: {
          deviceId: "zykh-qsm-001",
          syncSummary: {
            serviceUsers: [{ id: "u1" }],
            recentInquiries: [{ inquiry_id: "i1", title: "头晕问询", messageCount: 4 }],
          },
        },
      };
    }
    if (action === "LIST_MEDICINES") {
      return {
        result: [{
          slot: 1,
          hardwareSlot: 1,
          spec: medicinePatch.patch.spec,
          traceCode: medicinePatch.patch.traceCode,
          lowStockLine: medicinePatch.patch.lowStockLine,
          quantity: medicinePatch.patch.quantity,
          expireDate: medicinePatch.patch.expireDate,
          expiryPrecision: medicinePatch.patch.expiryPrecision,
        }],
      };
    }
    if (action === "GET_LATEST_VITALS") return { result: { heartRate: 72 } };
    if (action === "LIST_RECORDS") return { result: [] };
    throw new Error(action);
  };
  wx.cloud.database = () => {
    directDatabaseAccesses += 1;
    throw new Error("health snapshots must be read through membership-authorized cloud actions");
  };

  const sync = require(path.resolve(__dirname, "stationSync.js"));
  let snapshots = 0;
  const stop = sync.subscribeStationSnapshot(snapshot => {
    snapshots += 1;
    assert.equal(snapshot.compatibilityMode, true);
    assert.equal(snapshot.serviceUsers[0].id, "u1");
    assert.equal(snapshot.inquiries[0].messageCount, 4);
    assert.equal(Object.prototype.hasOwnProperty.call(snapshot.inquiries[0], "messages"), false);
    assert.deepEqual(snapshot.medicines[0], {
      slot: 1,
      hardwareSlot: 1,
      spec: medicinePatch.patch.spec,
      traceCode: medicinePatch.patch.traceCode,
      lowStockLine: medicinePatch.patch.lowStockLine,
      quantity: medicinePatch.patch.quantity,
      expireDate: medicinePatch.patch.expireDate,
      expiryPrecision: medicinePatch.patch.expiryPrecision,
    });
  }, error => { throw error; }, 5000);

  await new Promise(resolve => setTimeout(resolve, 80));
  assert.equal(snapshots >= 1, true);
  assert.equal(directDatabaseAccesses, 0);
  stop();
}

async function testMedicationSafetyReadHelper() {
  const calls = [];
  let directDatabaseAccesses = 0;
  global.wx = {
    getStorageSync: () => "",
    cloud: {
      database: () => {
        directDatabaseAccesses += 1;
        throw new Error("safety helper must not access collections directly");
      },
      callFunction: async ({ data }) => {
        calls.push(data);
        if (data.action === "PING") {
          return {
            result: {
              ok: true,
              schemaRevision: "2.5-caregiver-safety-events",
              capabilities: { medicationSafetyEvents: "v1" },
            },
          };
        }
        if (data.action === "LIST_MEDICATION_SAFETY_EVENTS") {
          return {
            result: {
              ok: true,
              items: [{
                event_id: "event-1",
                service_user_id: "wang-nainai",
                person_display_name: "王奶奶",
                medicine_name: "布洛芬缓释胶囊",
                check_status: "BLOCKED",
                dispense_status: "BLOCKED",
                caregiver_summary: "检测到禁忌，药箱未出药。",
                occurred_at: "2026-08-10 14:30:00",
                read: false,
              }],
              nextCursor: "cursor-2",
            },
          };
        }
        if (data.action === "GET_MEDICATION_SAFETY_EVENT") {
          return {
            result: {
              ok: true,
              event: {
                eventId: "event-1",
                personId: "wang-nainai",
                reasonCodes: ["CONDITION_CONTRAINDICATION"],
                read: false,
              },
            },
          };
        }
        if (data.action === "MARK_MEDICATION_SAFETY_EVENT_READ") {
          return { result: { ok: true, eventId: "event-1", state: "READ", readAt: "2026-08-10 15:00:00" } };
        }
        throw new Error(`unexpected action: ${data.action}`);
      },
    },
  };

  const safety = require(path.resolve(__dirname, "medicationSafetyEvents.js"));
  assert.deepEqual(
    safety.normalizeMedicationSafetyEvent({
      event_id: "event-corrupt",
      service_user_id: "wang-nainai",
      check_status: "CORRUPT",
      dispense_status: "MAYBE_OPENED",
    }),
    {
      eventId: "event-corrupt",
      personId: "wang-nainai",
      personName: "家庭成员",
      medicineId: "",
      medicineName: "未命名药品",
      slot: 0,
      checkStatus: "CHECK_FAILED",
      dispenseStatus: "NOT_STARTED",
      summary: "",
      occurredAt: "",
      read: false,
      reasonCodes: [],
      profileRevision: 0,
      rulesetVersion: "",
      medicineReviewFingerprint: "",
      qsmOperationId: "",
      physicalFailureSummary: "",
    },
    "unknown or incomplete event fields must fail closed without dropping the record",
  );
  for (const forbiddenExport of [
    "reportMedicationSafetyEvent",
    "approveMedication",
    "rejectMedication",
    "unblockMedication",
    "openFromSafetyEvent",
  ]) {
    assert.equal(Object.prototype.hasOwnProperty.call(safety, forbiddenExport), false);
  }

  const capability = await safety.getMedicationSafetyCapability();
  assert.deepEqual(capability, {
    supported: true,
    version: "v1",
    schemaRevision: "2.5-caregiver-safety-events",
  });
  const list = await safety.listMedicationSafetyEvents({
    personId: "wang-nainai",
    unreadOnly: true,
    limit: 10,
    cursor: "cursor-1",
  });
  assert.deepEqual(calls[1], {
    action: "LIST_MEDICATION_SAFETY_EVENTS",
    data: {
      deviceId: "zykh-qsm-001",
      personId: "wang-nainai",
      unreadOnly: true,
      limit: 10,
      cursor: "cursor-1",
    },
  });
  assert.deepEqual(list, {
    items: [{
      eventId: "event-1",
      personId: "wang-nainai",
      personName: "王奶奶",
      medicineId: "",
      medicineName: "布洛芬缓释胶囊",
      slot: 0,
      checkStatus: "BLOCKED",
      dispenseStatus: "BLOCKED",
      summary: "检测到禁忌，药箱未出药。",
      occurredAt: "2026-08-10 14:30:00",
      read: false,
      reasonCodes: [],
      profileRevision: 0,
      rulesetVersion: "",
      medicineReviewFingerprint: "",
      qsmOperationId: "",
      physicalFailureSummary: "",
    }],
    nextCursor: "cursor-2",
  });

  const detail = await safety.getMedicationSafetyEvent("event-1");
  assert.equal(detail.eventId, "event-1");
  assert.deepEqual(detail.reasonCodes, ["CONDITION_CONTRAINDICATION"]);
  const receipt = await safety.markMedicationSafetyEventRead("event-1");
  assert.equal(receipt.state, "READ");
  assert.equal(directDatabaseAccesses, 0);

  wx.cloud.callFunction = async () => ({ result: { ok: false, error: "CAREGIVER_MEMBERSHIP_REQUIRED" } });
  await assert.rejects(
    safety.listMedicationSafetyEvents(),
    /CAREGIVER_MEMBERSHIP_REQUIRED/,
    "membership failures must remain visible instead of becoming an empty list",
  );
}

async function testDeviceMembershipHelper() {
  const calls = [];
  let directDatabaseAccesses = 0;
  global.wx = {
    cloud: {
      database: () => {
        directDatabaseAccesses += 1;
        throw new Error("membership helper must not access collections directly");
      },
      callFunction: async ({ data }) => {
        calls.push(data);
        if (data.action === "PING") {
          return {
            result: {
              ok: true,
              capabilities: { devicePairing: "v1" },
              schemaRevision: "2.5-caregiver-safety-events",
            },
          };
        }
        if (data.action === "GET_MY_DEVICES") {
          return {
            result: {
              ok: true,
              items: [{
                deviceId: "binding-device-visible",
                name: "王奶奶家的药箱",
                online: true,
                lastSeenAt: "2026-08-10 09:59:59",
                role: "CAREGIVER",
                permissions: ["READ_SAFETY"],
                serviceUserScopes: ["wang-nainai"],
                deviceSecret: "must-not-leak-through-normalization",
              }],
            },
          };
        }
        if (data.action === "REDEEM_DEVICE_PAIRING_CODE") {
          return {
            result: {
              ok: true,
              deviceId: "binding-device-new",
              role: "VIEWER",
              permissions: ["READ_PLAN"],
              serviceUserScopes: [],
            },
          };
        }
        throw new Error(`unexpected action: ${data.action}`);
      },
    },
  };

  const helper = require(path.resolve(__dirname, "deviceMemberships.js"));
  const capability = await helper.getDevicePairingCapability();
  assert.deepEqual(capability, {
    supported: true,
    version: "v1",
    schemaRevision: "2.5-caregiver-safety-events",
  });
  const devices = await helper.getMyDevices();
  assert.deepEqual(calls[1], { action: "GET_MY_DEVICES", data: {} });
  assert.deepEqual(devices, [{
    deviceId: "binding-device-visible",
    name: "王奶奶家的药箱",
    online: true,
    lastSeenAt: "2026-08-10 09:59:59",
    role: "CAREGIVER",
    permissions: ["READ_SAFETY"],
    serviceUserScopes: ["wang-nainai"],
  }]);
  const redeemed = await helper.redeemDevicePairingCode("ZYKH-QSM-PAIR-20260810-A1");
  assert.deepEqual(calls[2], {
    action: "REDEEM_DEVICE_PAIRING_CODE",
    data: { pairingCode: "ZYKH-QSM-PAIR-20260810-A1" },
  });
  assert.deepEqual(redeemed, {
    deviceId: "binding-device-new",
    role: "VIEWER",
    permissions: ["READ_PLAN"],
    serviceUserScopes: [],
  });
  assert.equal(directDatabaseAccesses, 0);

  wx.cloud.callFunction = async () => ({ result: { ok: false, error: "PAIRING_CODE_INVALID" } });
  await assert.rejects(
    helper.redeemDevicePairingCode("ZYKH-QSM-PAIR-20260810-A1"),
    /PAIRING_CODE_INVALID/,
  );
  assert.equal(directDatabaseAccesses, 0);
}

Promise.resolve()
  .then(testCommandCompatibility)
  .then(testMedicationSafetyReadHelper)
  .then(testDeviceMembershipHelper)
  .then(testRealtimeSubscription)
  .then(() => console.log("miniprogram cloud sync contract: ok"))
  .catch(error => {
    console.error(error);
    process.exit(1);
  });
