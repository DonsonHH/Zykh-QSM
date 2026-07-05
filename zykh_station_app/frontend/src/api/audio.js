import { apiGet, apiPost } from "./client.js";

export function loadHostAudioStatus() {
  return apiGet("/api/audio/host/status");
}

export function readSpeech(duration = 4) {
  return apiPost("/api/audio/asr", { duration });
}

export function speakText(text, volume, speed = 1.18) {
  return apiPost("/api/audio/speak", { text, volume, speed });
}

export function playBeep(volume) {
  return apiPost("/api/audio/beep", { volume });
}

export function testAudioRelay(payload = {}) {
  return apiPost("/api/audio/relay-test", payload);
}

export function setHostMicVolume(volume) {
  return apiPost("/api/audio/host/mic-volume", { volume });
}
