import { apiGet, apiPost } from "./client.js";

export function loadHostAudioStatus() {
  return apiGet("/api/audio/host/status");
}

export function readSpeech(duration = 4) {
  return apiPost("/api/audio/asr", { duration });
}

export function speakText(text) {
  return apiPost("/api/audio/speak", { text });
}

export function playBeep() {
  return apiPost("/api/audio/beep", {});
}

export function testAudioRelay(payload = {}) {
  return apiPost("/api/audio/relay-test", payload);
}
