export function aiSourceLabel(source) {
  return aiSourcePresentation(source).label;
}

export function aiSourcePresentation(source) {
  const normalized = String(source || "").toLowerCase();
  if (normalized === "cloud" || normalized === "qsm_cloud") {
    return { kind: "smart", label: "智能回复" };
  }
  if (normalized === "local_llm") {
    return { kind: "local", label: "本地智能回复" };
  }
  if (["safety_rules", "rules_fallback", "local_fallback"].includes(normalized)) {
    return { kind: "safety", label: "安全提示" };
  }
  return { kind: "assistant", label: "问询回复" };
}
