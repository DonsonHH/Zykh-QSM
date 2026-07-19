export function normalizeVoiceTranscript(value) {
  return String(value || "").trim().replace(/[。．.]+$/u, "").trim();
}
