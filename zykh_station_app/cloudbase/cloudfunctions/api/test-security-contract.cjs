const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");

let inserted = 0;
const commandCollection = {
  add: async ({ data }) => {
    inserted += 1;
    return { _id: "command-1", data };
  },
};
const fakeCloud = {
  DYNAMIC_CURRENT_ENV: "test",
  init: () => {},
  getWXContext: () => ({ OPENID: "wechat-openid" }),
  database: () => ({ collection: () => commandCollection }),
};

const originalLoad = Module._load;
Module._load = function load(request, parent, isMain) {
  if (request === "wx-server-sdk") return fakeCloud;
  return originalLoad.call(this, request, parent, isMain);
};

const cloudFunction = require(path.resolve(__dirname, "index.js"));

async function run() {
  const source = fs.readFileSync(path.resolve(__dirname, "index.js"), "utf8");
  assert.match(source, /2\.2-vitals-history/, "vitals history schema revision was not advanced");
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
  console.log("cloud function command security contract: ok");
}

run().catch(error => {
  console.error(error);
  process.exit(1);
});
