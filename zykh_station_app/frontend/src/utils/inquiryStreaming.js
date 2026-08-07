export const LOCAL_REPLY_STREAM_PROFILE = Object.freeze({
  chunkSize: 8,
  intervalMs: 20
});

export const CLOUD_REPLY_STREAM_PROFILE = Object.freeze({
  chunkSize: 12,
  intervalMs: 16
});

const localReplySources = new Set(["offline_rules", "local_llm"]);

export function inquiryReplyStreamProfile(source) {
  const normalizedSource = String(source || "").trim().toLowerCase();
  return localReplySources.has(normalizedSource)
    ? LOCAL_REPLY_STREAM_PROFILE
    : CLOUD_REPLY_STREAM_PROFILE;
}
