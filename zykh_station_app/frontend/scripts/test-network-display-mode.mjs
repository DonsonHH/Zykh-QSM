import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { getNetworkIndicators, isLocalNetworkMode } from "../src/utils/network.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const settingsPage = await readFile(`${root}src/pages/Settings.jsx`, "utf8");
const adminDevices = await readFile(`${root}src/components/admin/AdminDevices.jsx`, "utf8");
const inquiryChat = await readFile(`${root}src/components/InquiryChatStep.jsx`, "utf8");

const hiddenNetwork = {
  mode: "sim",
  transport: "sim",
  display_mode: "local",
  ai_mode: "cloud",
  wifi_connected: false,
  sim_connected: true,
  sim_enabled: false
};

assert.equal(
  isLocalNetworkMode(hiddenNetwork),
  true,
  "local display mode must hide the physical network icons"
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

assert.doesNotMatch(
  settingsPage,
  /wifi_enabled|sim_enabled|切换 Wi-Fi|切换数据网络/,
  "basic settings still exposes physical network controls"
);
assert.match(adminDevices, /updateAdminNetwork/, "device console is missing real network controls");
assert.doesNotMatch(
  inquiryChat,
  /isLocalNetworkMode/,
  "display mode still changes inquiry audio or presentation behavior"
);

console.log("network display mode contract: ok");
