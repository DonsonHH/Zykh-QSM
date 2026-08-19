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

export function startVitalsSession({ replaceActive = true, sourceRoute = "HOME", inquirySessionId = "" } = {}) {
  return apiPost("/api/vitals/session/start", {
    replace_active: replaceActive,
    source_route: sourceRoute,
    inquiry_session_id: inquirySessionId
  });
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

export async function turnOffCabinetLight() {
  const response = await apiPost("/api/qsm/cabinet-light/off", {});
  if (response?.ok !== true) {
    throw new Error(response?.message || "分类柜指示灯关闭结果未确认");
  }
  return response;
}

export function loadQsmCapabilities() {
  return apiGet("/api/qsm/capabilities");
}
