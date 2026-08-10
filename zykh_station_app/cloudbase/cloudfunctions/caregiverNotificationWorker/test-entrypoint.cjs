const assert = require("node:assert/strict");
const fs = require("node:fs");
const Module = require("node:module");
const path = require("node:path");
const test = require("node:test");

test("the standalone cloud function rejects miniprogram invocation and declares timer/openapi", async () => {
  let currentOpenId = "miniprogram-openid";
  let databaseTouches = 0;
  const fakeCloud = {
    DYNAMIC_CURRENT_ENV: "test",
    init() {},
    getWXContext: () => ({ OPENID: currentOpenId }),
    database: () => ({
      collection() {
        databaseTouches += 1;
        throw new Error("database must not be touched by a rejected invocation");
      },
      runTransaction() {
        databaseTouches += 1;
        throw new Error("database must not be touched by a rejected invocation");
      },
    }),
    openapi: {
      subscribeMessage: {
        send: async () => { throw new Error("provider must not be touched"); },
      },
    },
  };
  const originalLoad = Module._load;
  Module._load = function load(request, parent, isMain) {
    if (request === "wx-server-sdk") return fakeCloud;
    return originalLoad.call(this, request, parent, isMain);
  };
  let entrypoint;
  try {
    entrypoint = require(path.resolve(__dirname, "index.js"));
  } finally {
    Module._load = originalLoad;
  }

  const rejected = await entrypoint.main({
    Type: "Timer",
    TriggerName: "caregiver-notification-worker-timer",
  });
  assert.deepEqual(rejected, { ok: false, error: "WORKER_INVOCATION_FORBIDDEN" });
  assert.equal(databaseTouches, 0);

  currentOpenId = "";
  const config = JSON.parse(fs.readFileSync(path.resolve(__dirname, "config.json"), "utf8"));
  assert.deepEqual(config.permissions.openapi, ["subscribeMessage.send"]);
  assert.equal(config.triggers.length, 1);
  assert.equal(config.triggers[0].name, "caregiver-notification-worker-timer");
  assert.equal(config.triggers[0].type, "timer");
  const packageData = JSON.parse(fs.readFileSync(path.resolve(__dirname, "package.json"), "utf8"));
  assert.equal(packageData.main, "index.js");
  assert.equal(packageData.dependencies["wx-server-sdk"], "~2.6.3");
});
