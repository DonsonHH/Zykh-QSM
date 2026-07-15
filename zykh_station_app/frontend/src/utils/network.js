export function isLocalNetworkMode(networkStatus) {
  const mode = String(networkStatus?.mode || "").toLowerCase();
  const transport = String(networkStatus?.transport || "").toLowerCase();
  const aiMode = String(networkStatus?.ai_mode || "").toLowerCase();
  const label = String(networkStatus?.label || "");

  return (
    mode === "local" ||
    mode === "offline" ||
    transport === "local" ||
    aiMode === "local_llm" ||
    aiMode === "rules_fallback" ||
    aiMode === "local_fallback" ||
    label.includes("本地")
  );
}

export function getNetworkIndicators(networkStatus) {
  const explicitLocalMode = isLocalNetworkMode(networkStatus);
  const rawWifiConnected = Boolean(networkStatus?.wifi_connected || networkStatus?.wifi?.connected);
  const rawSimConnected = Boolean(networkStatus?.sim_connected || networkStatus?.sim?.connected);
  const rawSimPresent = Boolean(networkStatus?.sim_present || networkStatus?.sim?.present || rawSimConnected);
  const wifiConnected = explicitLocalMode ? false : rawWifiConnected;
  const simConnected = explicitLocalMode ? false : rawSimConnected;
  const simPresent = explicitLocalMode ? false : rawSimPresent;
  const wifiSignal = explicitLocalMode
    ? "none"
    : networkStatus?.wifi_signal || networkStatus?.wifi?.signal || (wifiConnected ? "good" : "none");
  const simSignal = explicitLocalMode
    ? "none"
    : networkStatus?.sim_signal || networkStatus?.sim?.signal || (simConnected ? "good" : simPresent ? "weak" : "none");
  const wifiBars = explicitLocalMode ? 0 : normalizeBars(networkStatus?.wifi_signal_bars ?? networkStatus?.wifi?.bars);
  const simBars = explicitLocalMode ? 0 : normalizeBars(networkStatus?.sim_signal_bars ?? networkStatus?.sim?.bars);
  const wifiTone = wifiBars >= 3 ? "good" : wifiConnected ? "weak" : "offline";
  const simTone = simBars >= 3 ? "good" : simPresent ? "weak" : "offline";
  const wifiDbm = numberOrNull(networkStatus?.wifi_signal_dbm ?? networkStatus?.wifi?.dbm);
  const simDbm = numberOrNull(networkStatus?.sim_signal_dbm ?? networkStatus?.sim?.dbm);
  const wifiPercent = normalizePercent(networkStatus?.wifi_signal_percent ?? networkStatus?.wifi?.percent);
  const simPercent = normalizePercent(networkStatus?.sim_signal_percent ?? networkStatus?.sim?.percent);

  return {
    localMode: explicitLocalMode || (!wifiConnected && !simConnected),
    wifi: {
      connected: wifiConnected,
      tone: wifiTone,
      bars: wifiBars,
      dbm: wifiDbm,
      percent: wifiPercent,
      label: signalLabel("WiFi", wifiConnected, wifiBars, wifiDbm, wifiPercent)
    },
    sim: {
      connected: simConnected,
      present: simPresent,
      tone: simTone,
      bars: simBars,
      dbm: simDbm,
      percent: simPercent,
      label: signalLabel("SIM", simConnected, simBars, simDbm, simPercent)
    }
  };
}

function normalizeBars(value) {
  const bars = Number(value);
  return Number.isFinite(bars) ? Math.max(0, Math.min(4, Math.round(bars))) : 0;
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
    const localModelReady = Boolean(networkStatus?.local_ai?.ready) || networkStatus?.ai_mode === "local_llm";
    return {
      title: "离线模式",
      status: localModelReady ? "离线模型可用" : "安全规则可用",
      detail: localModelReady
        ? "联网功能未使用，问询由设备内离线模型完成。"
        : "离线模型暂未就绪，当前仅执行本地安全规则。"
    };
  }

  return {
    title: networkStatus?.transport === "wifi" ? "WiFi" : "SIM",
    status: networkStatus?.label || "联网状态",
    detail: "保持当前联网状态。"
  };
}
