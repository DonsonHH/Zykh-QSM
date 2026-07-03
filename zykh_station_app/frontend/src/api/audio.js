import { apiPost } from "./client.js";

export function readSpeech(duration = 4) {
  return apiPost("/api/audio/asr", { duration });
}

export function speakText(text) {
  return apiPost("/api/audio/speak", { text });
}

export function playBeep() {
  return apiPost("/api/audio/beep", {});
}
