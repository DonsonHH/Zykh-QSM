export function aiSourceLabel(source) {
  return aiSourcePresentation(source).label;
}

export function aiSourcePresentation(source) {
  const normalized = String(source || "").toLowerCase();
  if (["cloud", "cloud_responses", "cloud_chat_fallback", "qsm_cloud"].includes(normalized)) {
    return { kind: "smart", label: "智能回复" };
  }
  if (["local_llm", "offline_rules"].includes(normalized)) {
    return { kind: "smart", label: "智能回复" };
  }
  if (["safety_rules", "rules_fallback", "local_fallback"].includes(normalized)) {
    return { kind: "safety", label: "安全提示" };
  }
  return { kind: "assistant", label: "问询回复" };
}
