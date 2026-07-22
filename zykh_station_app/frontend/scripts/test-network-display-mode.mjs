import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { getNetworkIndicators, isLocalNetworkMode } from "../src/utils/network.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const settingsPage = await readFile(`${root}src/pages/Settings.jsx`, "utf8");

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

const localDisplayWithLiveSim = getNetworkIndicators({
  mode: "local",
  transport: "local",
  ai_mode: "cloud",
  wifi_connected: true,
  sim_enabled: true,
  sim_connected: true,
  qsm_sim_connected: true,
  sim_signal_bars: 4
});
assert.equal(localDisplayWithLiveSim.localMode, true);
assert.equal(localDisplayWithLiveSim.wifi.connected, false);
assert.equal(localDisplayWithLiveSim.sim.connected, false);
assert.equal(localDisplayWithLiveSim.sim.enabled, false);

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

assert.match(
  settingsPage,
  /SettingsSwitch[\s\S]{0,80}checked=\{simDisplayEnabled\}[\s\S]{0,100}onChange=\{setSimDisplayEnabled\}/,
  "the settings SIM demo switch cannot change its displayed state"
);
assert.doesNotMatch(
  settingsPage,
  /SettingsSwitch[^\n]*update\("sim_enabled"/,
  "the settings SIM demo switch still changes the live network setting"
);

console.log("network display mode contract: ok");
