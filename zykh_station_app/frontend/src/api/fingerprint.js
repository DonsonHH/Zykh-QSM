import { apiDelete, apiGet, apiPost } from "./client.js";

export function loadFingerprintStatus() {
  return apiGet("/api/fingerprint/status");
}

export function identifyFingerprint(timeout = 45) {
  return apiPost(`/api/fingerprint/identify?timeout=${timeout}`, {});
}

export function setFingerprintStandby() {
  return apiPost("/api/fingerprint/standby", {});
}

export function wakeFingerprint() {
  return apiPost("/api/fingerprint/wake", {});
}

export function enrollFingerprint(userId, timeout = 45) {
  return apiPost(`/api/fingerprint/enroll/${encodeURIComponent(userId)}?timeout=${timeout}`, {});
}

export function deleteFingerprint(userId) {
  return apiDelete(`/api/fingerprint/${encodeURIComponent(userId)}`);
}
