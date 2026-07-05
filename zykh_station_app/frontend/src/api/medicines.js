import { apiGet, apiPatch } from "./client.js";

export function loadMedicines() {
  return apiGet("/api/medicines");
}

export function loadMedicine(medicineId) {
  return apiGet(`/api/medicines/${medicineId}`);
}

export function updateMedicine(medicineId, payload) {
  return apiPatch(`/api/medicines/${medicineId}`, payload);
}
