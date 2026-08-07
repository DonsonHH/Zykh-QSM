export const LOCAL_REPLY_STREAM_PROFILE = Object.freeze({
  chunkSize: 1,
  intervalMs: 72
});

export const CLOUD_REPLY_STREAM_PROFILE = Object.freeze({
  chunkSize: 4,
  intervalMs: 42
});

const localReplySources = new Set(["offline_rules", "local_llm"]);

export function inquiryReplyStreamProfile(source) {
  const normalizedSource = String(source || "").trim().toLowerCase();
  return localReplySources.has(normalizedSource)
    ? LOCAL_REPLY_STREAM_PROFILE
    : CLOUD_REPLY_STREAM_PROFILE;
}
