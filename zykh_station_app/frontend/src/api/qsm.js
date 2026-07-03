import { apiGet, apiPost } from "./client.js";

export function loadQsmStatus() {
  return apiGet("/api/qsm/status");
}

export function loadQsmVitals() {
  return apiGet("/api/qsm/vitals");
}

export function captureQsmCamera() {
  return apiPost("/api/qsm/camera/capture", {});
}

export function dryRunQsmDispense(payload) {
  return apiPost("/api/qsm/dispense/dry-run", payload);
}

export function loadQsmCapabilities() {
  return apiGet("/api/qsm/capabilities");
}
