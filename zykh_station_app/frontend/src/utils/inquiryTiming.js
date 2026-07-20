export const OFFLINE_REPLY_MIN_DELAY_MS = 3000;

export function offlineReplyDelayMs(source, elapsedMs, nextAction = "ask") {
  if (source !== "offline_rules" || nextAction === "escalate") return 0;
  return Math.max(0, OFFLINE_REPLY_MIN_DELAY_MS - Math.max(0, elapsedMs));
}
