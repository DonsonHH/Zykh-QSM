export function aiSourceLabel(source) {
  const normalized = String(source || "").toLowerCase();
  if (normalized === "cloud" || normalized === "qsm_cloud") {
    return "云通道";
  }
  if (normalized === "local_llm") {
    return "离线模型";
  }
  if (["safety_rules", "rules_fallback", "local_fallback"].includes(normalized)) {
    return "安全规则";
  }
  return "问询助手";
}
