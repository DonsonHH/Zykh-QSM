import { apiGet, apiPatch, apiPost } from "./client.js";

export function loadMedicines() {
  return apiGet("/api/medicines");
}

export function loadMedicine(medicineId) {
  return apiGet(`/api/medicines/${medicineId}`);
}

export function updateMedicine(medicineId, payload) {
  return apiPatch(`/api/medicines/${medicineId}`, payload);
}

export function confirmMedicineInventory(medicineId, payload) {
  return apiPost(`/api/medicines/${medicineId}/inventory-confirmation`, payload);
}
