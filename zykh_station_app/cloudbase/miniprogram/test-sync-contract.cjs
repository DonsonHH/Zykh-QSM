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
  const legacy = await commands.createCommand("AUDIO_BEEP", {});
  assert.equal(legacy.compatibilityMode, true);
  assert.equal(writes, 1);

  wx.cloud.callFunction = async () => ({ result: { _id: "v2-command", status: "pending" } });
  const v2 = await commands.createCommand("AUDIO_BEEP", {});
  assert.equal(v2._id, "v2-command");
  assert.equal(writes, 1);

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
    assert.equal(writes, 1, `${message} must not fall back to a direct database write`);
  }

  wx.cloud.callFunction = async () => ({ result: { ok: false, error: "unknown action: CREATE_COMMAND" } });
  const legacyFromV1Result = await commands.createCommand("AUDIO_BEEP", {});
  assert.equal(legacyFromV1Result.compatibilityMode, true);
  assert.equal(writes, 2);

  wx.cloud.callFunction = async () => ({ result: { ok: false, error: "medicine payload validation failed" } });
  await assert.rejects(commands.createCommand("UPSERT_MEDICINE", {}), /validation failed/);
  assert.equal(writes, 2);
}

async function testRealtimeSubscription() {
  const watched = [];
  let closed = 0;
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
  wx.cloud.database = () => ({
    collection: name => {
      const query = {
        where: () => query,
        orderBy: () => query,
        limit: () => query,
        watch: () => {
          watched.push(name);
          return { close: () => { closed += 1; } };
        },
      };
      return query;
    },
  });

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
  assert.deepEqual(watched.sort(), ["commands", "devices", "medicines", "records", "vitals"]);
  stop();
  assert.equal(closed, 5);
}

Promise.resolve()
  .then(testCommandCompatibility)
  .then(testRealtimeSubscription)
  .then(() => console.log("miniprogram cloud sync contract: ok"))
  .catch(error => {
    console.error(error);
    process.exit(1);
  });
