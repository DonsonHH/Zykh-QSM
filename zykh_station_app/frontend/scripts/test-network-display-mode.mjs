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

const qsmConnectedWithWifi = getNetworkIndicators({
  mode: "wifi",
  transport: "wifi",
  ai_mode: "cloud",
  wifi_connected: true,
  sim_connected: false,
  qsm_sim_connected: true,
  host_tether_ready: false,
  sim_present: true,
  sim_enabled: true,
  sim_signal_bars: 4
});
assert.equal(qsmConnectedWithWifi.localMode, false);
assert.equal(qsmConnectedWithWifi.sim.connected, true);
assert.equal(qsmConnectedWithWifi.sim.bars, 4);

console.log("network display mode contract: ok");
