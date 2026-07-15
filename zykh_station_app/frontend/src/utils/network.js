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
  const wifiTone = wifiSignal === "good" ? "good" : wifiConnected ? "weak" : "offline";
  const simTone = simSignal === "good" ? "good" : simPresent ? "weak" : "offline";

  return {
    localMode: explicitLocalMode || (!wifiConnected && !simConnected),
    wifi: {
      connected: wifiConnected,
      tone: wifiTone,
      label: wifiTone === "good" ? "WiFi 网络良好" : wifiTone === "weak" ? "WiFi 信号偏弱" : "WiFi 未连接"
    },
    sim: {
      connected: simConnected,
      present: simPresent,
      tone: simTone,
      label: simTone === "good" ? "SIM 网络良好" : simTone === "weak" ? "SIM 信号偏弱" : "SIM 未连接"
    }
  };
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
