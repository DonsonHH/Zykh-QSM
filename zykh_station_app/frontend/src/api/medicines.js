import { apiGet } from "./client.js";

export function loadMedicines() {
  return apiGet("/api/medicines");
}

export function loadMedicine(medicineId) {
  return apiGet(`/api/medicines/${medicineId}`);
}
