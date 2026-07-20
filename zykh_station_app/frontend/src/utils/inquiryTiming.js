export const OFFLINE_REPLY_MIN_DELAY_MS = 3000;

const localReplySources = new Set(["offline_rules", "local_llm"]);

export function offlineReplyDelayMs(source, localMode = false) {
  const normalizedSource = String(source || "").trim().toLowerCase();
  if (!localMode && !localReplySources.has(normalizedSource)) return 0;
  return OFFLINE_REPLY_MIN_DELAY_MS;
}
