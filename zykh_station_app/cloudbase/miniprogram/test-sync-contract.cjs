const assert = require("node:assert/strict");
const path = require("node:path");

global.getApp = () => ({ globalData: { deviceId: "zykh-qsm-001" } });

async function testCommandCompatibility() {
  let writes = 0;
  global.wx = {
    getStorageSync: () => "",
    cloud: {
      callFunction: async () => { throw new Error("unknown action"); },
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
}

async function testRealtimeSubscription() {
  const watched = [];
  let closed = 0;
  wx.cloud.callFunction = async ({ data }) => {
    const action = data.action;
    if (action === "GET_SNAPSHOT") throw new Error("v1");
    if (action === "PING") return { result: { ok: true } };
    if (action === "GET_DEVICE") {
      return { result: { deviceId: "zykh-qsm-001", syncSummary: { serviceUsers: [{ id: "u1" }] } } };
    }
    if (action === "LIST_MEDICINES") return { result: [{ slot: 1 }] };
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
