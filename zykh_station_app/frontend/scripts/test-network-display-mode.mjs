import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import {
  DEFAULT_NETWORK_STATUS,
  getNetworkIndicators,
  isLocalNetworkMode
} from "../src/utils/network.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const settingsPage = await readFile(`${root}src/pages/Settings.jsx`, "utf8");
const adminDevices = await readFile(`${root}src/components/admin/AdminDevices.jsx`, "utf8");
const adminOverview = await readFile(`${root}src/components/admin/AdminOverview.jsx`, "utf8");
const inquiryChat = await readFile(`${root}src/components/InquiryChatStep.jsx`, "utf8");
const inquiryReview = await readFile(`${root}src/components/InquiryInformationReview.jsx`, "utf8");
const inquiryResult = await readFile(`${root}src/components/InquiryResultStep.jsx`, "utf8");
const syncStatusCard = await readFile(`${root}src/components/SyncStatusCard.jsx`, "utf8");
const systemCheck = await readFile(`${root}src/components/SystemCheckModal.jsx`, "utf8");
const aiPresentation = await readFile(`${root}src/utils/ai.js`, "utf8");

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
assert.equal(
  qsmConnectedWithWifi.activeTransport,
  "wifi",
  "the top bar must identify WiFi as the active link when it is the default transport"
);

const pendingNetwork = getNetworkIndicators(DEFAULT_NETWORK_STATUS);
assert.equal(DEFAULT_NETWORK_STATUS.ok, false);
assert.equal(DEFAULT_NETWORK_STATUS.pending, true);
assert.equal(pendingNetwork.pending, true);
assert.equal(pendingNetwork.localMode, false);
assert.equal(
  pendingNetwork.wifi.connected,
  false,
  "the first paint must not claim a physical WiFi connection before the status response arrives"
);
assert.equal(pendingNetwork.sim.connected, false);
assert.equal(pendingNetwork.activeTransport, "");

const simulated4g = getNetworkIndicators({
  mode: "wifi",
  transport: "wifi",
  wifi_connected: true,
  wifi_signal: "good",
  wifi_signal_bars: 4,
  sim_enabled: true,
  sim_present: true,
  sim_connected: true,
  sim_signal: "good",
  sim_signal_bars: 3,
  simulated: true,
  source: "simulation"
});
assert.equal(simulated4g.wifi.connected, true);
assert.equal(simulated4g.activeTransport, "wifi");
assert.equal(simulated4g.sim.enabled, true);
assert.equal(simulated4g.sim.connected, true);
assert.equal(simulated4g.sim.bars, 3);
assert.equal(simulated4g.sim.tone, "good");
assert.match(simulated4g.sim.label, /^4G 信号良好/);

const app = await readFile(`${root}src/App.jsx`, "utf8");
const launcher = await readFile(`${root}../scripts/launch_kiosk.sh`, "utf8");
assert.match(app, /useState\(DEFAULT_NETWORK_STATUS\)/, "the top bar must start with the explicit pending network state");
assert.equal(
  (app.match(/loadNetworkStatus\(\)\.then\(updateNetworkStatus\)\.catch\(\(\) => undefined\)/g) || []).length,
  2,
  "initial and polling failures must preserve the initial default or last known network state"
);
assert.doesNotMatch(
  app,
  /catch\(\(\) => updateNetworkStatus\(DEFAULT_NETWORK_STATUS\)\)/,
  "a transient failure must never overwrite a known real status with the simulated default"
);
assert.match(launcher, /KIOSK_INSTALL_QSM_TETHER:-0/, "kiosk must not install the 4G tether helper by default");
assert.match(launcher, /KIOSK_QSM_TETHER:-0/, "kiosk must not start the physical 4G tether by default");

assert.doesNotMatch(
  settingsPage,
  /wifi_enabled|sim_enabled|切换 Wi-Fi|切换数据网络/,
  "basic settings still exposes physical network controls"
);
assert.match(settingsPage, /联网模式/, "settings is missing the online presentation mode");
assert.match(settingsPage, /断网模式/, "settings is missing the offline presentation mode");
assert.doesNotMatch(
  settingsPage,
  /仅改变显示与同步|不会切换实际|小程序实时连接|本地模式|显示网络图标|暂停同步/,
  "demo settings exposes internal implementation details"
);
assert.match(adminDevices, /updateAdminNetwork/, "device console is missing real network controls");
assert.match(
  adminDevices,
  /const networkSimulated = Boolean\(networkSettings\?\.network_simulated \?\? network\.simulated\)/,
  "device console does not use settings provenance with overview fallback"
);
assert.match(
  adminDevices,
  /networkSimulated \? "网络与临时 4G 展示" : "物理网络"/,
  "simulated 4G is still presented as a physical network panel"
);
assert.match(
  adminDevices,
  /4G 开关仅保存本地展示状态，不连接或控制物理模块/,
  "simulated 4G controls do not disclose their local-only behavior"
);
assert.match(
  adminDevices,
  /networkSimulated \? "切换临时 4G 展示状态" : "真实切换数据网络"/,
  "the simulated 4G switch still claims to control the physical data network"
);
assert.match(
  adminDevices,
  /临时展示已开启|临时展示已关闭/,
  "simulated 4G status still claims a physical connection"
);
assert.doesNotMatch(
  adminOverview,
  /问询模式|云端问询|本地问询/,
  "admin overview exposes the hidden model route"
);
assert.doesNotMatch(
  inquiryChat,
  /isLocalNetworkMode/,
  "display mode still changes inquiry audio or presentation behavior"
);
assert.doesNotMatch(
  inquiryReview,
  /isLocalNetworkMode|\?\s*["']offline["']\s*:\s*["']auto["']/,
  "display mode still changes review audio behavior"
);
assert.doesNotMatch(
  inquiryResult,
  /isLocalNetworkMode|\?\s*["']offline["']\s*:\s*["']auto["']/,
  "display mode still changes result audio behavior"
);
for (const [name, source] of [
  ["chat", inquiryChat],
  ["review", inquiryReview],
  ["result", inquiryResult]
]) {
  assert.doesNotMatch(
    source,
    /speechSynthesis|SpeechSynthesisUtterance/,
    `${name} still bypasses the managed speech route with browser TTS`
  );
}
assert.doesNotMatch(
  syncStatusCard,
  /实时同步已暂停|切换到联网模式后/,
  "records UI exposes the hidden synchronization route"
);
assert.match(systemCheck, /isLocalNetworkMode/, "system check does not mask physical links in local display mode");
assert.match(systemCheck, /断网模式/, "system check is missing the local presentation label");
assert.doesNotMatch(
  aiPresentation,
  /本地智能回复|云端智能回复/,
  "inquiry source badges expose the hidden model route"
);

console.log("network display mode contract: ok");
