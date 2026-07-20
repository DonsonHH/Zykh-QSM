import assert from "node:assert/strict";

import { getNetworkIndicators, isLocalNetworkMode } from "../src/utils/network.js";

const hiddenNetwork = {
  mode: "sim",
  transport: "sim",
  ai_mode: "cloud",
  wifi_connected: false,
  sim_connected: true,
  sim_enabled: false
};

assert.equal(
  isLocalNetworkMode(hiddenNetwork),
  true,
  "hidden Wi-Fi/SIM controls must keep local ASR and TTS selected"
);
const indicators = getNetworkIndicators(hiddenNetwork);
assert.equal(indicators.localMode, true);
assert.equal(indicators.wifi.connected, false);
assert.equal(indicators.sim.enabled, false);

console.log("network display mode contract: ok");
