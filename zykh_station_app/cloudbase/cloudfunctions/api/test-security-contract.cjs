const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");

let inserted = 0;
const insertedRows = [];
const stores = new Map();
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
        if (!store.has(id)) throw new Error("missing document");
        return { data: Object.assign({ _id: id }, store.get(id)) };
      },
      set: async ({ data }) => { store.set(id, data); },
      remove: async () => { store.delete(id); },
    }),
  });
}
const fakeCloud = {
  DYNAMIC_CURRENT_ENV: "test",
  init: () => {},
  getWXContext: () => ({ OPENID: "wechat-openid" }),
  database: () => ({ collection }),
};

const originalLoad = Module._load;
Module._load = function load(request, parent, isMain) {
  if (request === "wx-server-sdk") return fakeCloud;
  return originalLoad.call(this, request, parent, isMain);
};

const cloudFunction = require(path.resolve(__dirname, "index.js"));

async function run() {
  const source = fs.readFileSync(path.resolve(__dirname, "index.js"), "utf8");
  assert.match(source, /2\.4-medicine-safety-contract/, "medicine safety schema revision was not advanced");
  assert.match(
    source,
    /normalized\.createdAt = firstPresent\(\s*row\.measured_at/,
    "vitals history is sorted by synchronization time instead of measurement time",
  );
  assert.match(
    source,
    /vitals: await tryListRows\(collections\.vitals/,
    "station snapshots do not expose vitals history",
  );

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
  const batch = await cloudFunction.main({
    action: "UPSERT_SNAPSHOT_BATCH",
    data: {
      deviceId: "zykh-qsm-001",
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
  console.log("cloud function command security contract: ok");
}

run().catch(error => {
  console.error(error);
  process.exit(1);
});
