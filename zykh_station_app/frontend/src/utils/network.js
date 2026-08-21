export const DEFAULT_NETWORK_STATUS = Object.freeze({
  ok: true,
  mode: "sim",
  transport: "sim",
  status: "good",
  signal: "good",
  label: "4G 已连接",
  display_mode: "online",
  realtime_sync_enabled: true,
  ai_mode: "cloud",
  wifi_connected: true,
  wifi_signal: "good",
  wifi_signal_bars: 3,
  wifi_signal_level: "good",
  sim_enabled: true,
  sim_present: true,
  sim_connected: true,
  qsm_sim_connected: false,
  host_tether_ready: false,
  sim_signal: "good",
  sim_signal_bars: 3,
  sim_signal_level: "good",
  simulated: true,
  source: "simulation"
});

export function isLocalNetworkMode(networkStatus) {
  const displayMode = String(networkStatus?.display_mode || "").toLowerCase();
  if (displayMode) return displayMode === "local";
  const mode = String(networkStatus?.mode || "").toLowerCase();
  const transport = String(networkStatus?.transport || "").toLowerCase();
  const aiMode = String(networkStatus?.ai_mode || "").toLowerCase();
  const label = String(networkStatus?.label || "");
  const wifiConnected = Boolean(
    networkStatus?.wifi_connected || networkStatus?.wifi?.connected
  );
  const simEnabled = networkStatus?.sim_enabled ?? networkStatus?.sim?.enabled ?? true;

  return (
    mode === "local" ||
    mode === "offline" ||
    transport === "local" ||
    aiMode === "local_llm" ||
    aiMode === "offline_rules" ||
    aiMode === "rules_fallback" ||
    aiMode === "local_fallback" ||
    label.includes("本地") ||
    (!wifiConnected && simEnabled === false)
  );
}

export function getNetworkIndicators(networkStatus) {
  const explicitLocalMode = isLocalNetworkMode(networkStatus);
  const rawWifiConnected = Boolean(networkStatus?.wifi_connected || networkStatus?.wifi?.connected);
  const rawSimConnected = Boolean(
    networkStatus?.sim_connected ||
    networkStatus?.qsm_sim_connected ||
    networkStatus?.sim?.connected
  );
  const rawSimPresent = Boolean(networkStatus?.sim_present || networkStatus?.sim?.present || rawSimConnected);
  const rawSimEnabled = networkStatus?.sim_enabled ?? networkStatus?.sim?.enabled ?? true;
  const wifiConnected = explicitLocalMode ? false : rawWifiConnected;
  const simEnabled = !explicitLocalMode && Boolean(rawSimEnabled);
  const simConnected = simEnabled && rawSimConnected;
  const simPresent = simEnabled && rawSimPresent;
  const wifiSignal = explicitLocalMode
    ? "none"
    : networkStatus?.wifi_signal || networkStatus?.wifi?.signal || (wifiConnected ? "good" : "none");
  const simSignal = explicitLocalMode
    ? "none"
    : networkStatus?.sim_signal || networkStatus?.sim?.signal || (simConnected ? "good" : simPresent ? "weak" : "none");
  const wifiBars = explicitLocalMode
    ? 0
    : normalizeBars(networkStatus?.wifi_signal_bars ?? networkStatus?.wifi?.bars, wifiConnected ? 2 : 0);
  const simBars = explicitLocalMode
    ? 0
    : normalizeBars(networkStatus?.sim_signal_bars ?? networkStatus?.sim?.bars, simConnected ? 2 : 0);
  const wifiTone = wifiBars >= 3 ? "good" : wifiConnected ? "weak" : "offline";
  const simTone = simBars >= 3 ? "good" : simPresent ? "weak" : "offline";
  const wifiDbm = numberOrNull(networkStatus?.wifi_signal_dbm ?? networkStatus?.wifi?.dbm);
  const simDbm = numberOrNull(networkStatus?.sim_signal_dbm ?? networkStatus?.sim?.dbm);
  const wifiPercent = normalizePercent(networkStatus?.wifi_signal_percent ?? networkStatus?.wifi?.percent);
  const simPercent = normalizePercent(networkStatus?.sim_signal_percent ?? networkStatus?.sim?.percent);

  return {
    localMode: explicitLocalMode || (!wifiConnected && !simConnected && !simEnabled),
    wifi: {
      connected: wifiConnected,
      tone: wifiTone,
      bars: wifiBars,
      dbm: wifiDbm,
      percent: wifiPercent,
      label: signalLabel("WiFi", wifiConnected, wifiBars, wifiDbm, wifiPercent)
    },
    sim: {
      enabled: simEnabled,
      connected: simConnected,
      present: simPresent,
      tone: simTone,
      bars: simBars,
      dbm: simDbm,
      percent: simPercent,
      label: signalLabel("4G", simConnected, simBars, simDbm, simPercent)
    }
  };
}

function normalizeBars(value, fallback = 0) {
  const bars = Number(value);
  return Number.isFinite(bars) ? Math.max(0, Math.min(4, Math.round(bars))) : fallback;
}

function normalizePercent(value) {
  const percent = Number(value);
  return Number.isFinite(percent) ? Math.max(0, Math.min(100, Math.round(percent))) : 0;
}

function numberOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function signalLabel(name, connected, bars, dbm, percent) {
  if (!connected) {
    return `${name} 未连接`;
  }
  const level = bars >= 4 ? "信号优秀" : bars === 3 ? "信号良好" : bars === 2 ? "信号一般" : bars === 1 ? "信号较弱" : "信号强度未知";
  const detail = dbm == null ? "" : `，${dbm} dBm / ${percent}%`;
  return `${name} ${level}${detail}`;
}

export function localNetworkCopy(networkStatus) {
  if (isLocalNetworkMode(networkStatus)) {
    return {
      title: "本地模式",
      status: "设备运行正常",
      detail: "当前数据已保存在设备中。"
    };
  }

  return {
    title: networkStatus?.transport === "wifi" ? "WiFi" : "4G",
    status: networkStatus?.label || "联网状态",
    detail: "保持当前联网状态。"
  };
}
