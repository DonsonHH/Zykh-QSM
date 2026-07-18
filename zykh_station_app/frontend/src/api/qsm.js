import { apiGet, apiPost } from "./client.js";

export function loadQsmStatus() {
  return apiGet("/api/qsm/status");
}

export function loadQsmVitals() {
  return apiPost("/api/vitals/read-all", {});
}

export function prepareQsmVitals() {
  return apiPost("/api/vitals/prepare", {});
}

export function startVitalsSession() {
  return apiPost("/api/vitals/session/start", {});
}

export function loadVitalsSession(sessionId) {
  return apiGet(`/api/vitals/session/${encodeURIComponent(sessionId)}`);
}

export function cancelVitalsSession(sessionId) {
  return apiPost(`/api/vitals/session/${encodeURIComponent(sessionId)}/cancel`, {});
}

export function captureQsmCamera() {
  return apiPost("/api/camera/capture", {});
}

export function scanMedicine(payload = {}) {
  return apiPost("/api/medicine/scan", payload);
}

export function scanMedicineFrame(payload = {}) {
  return apiPost("/api/medicine/scan-frame", payload);
}

export function registerScannedMedicine(payload = {}) {
  return apiPost("/api/medicine/scan/register", payload);
}

export function dryRunQsmDispense(payload) {
  return apiPost("/api/qsm/dispense/dry-run", payload);
}

export function loadQsmCapabilities() {
  return apiGet("/api/qsm/capabilities");
}
