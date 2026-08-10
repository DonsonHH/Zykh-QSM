import { apiGet, apiPost } from "./client.js";

export function confirmDispense(payload) {
  return apiPost("/api/dispense/confirm", payload);
}

export function assessManualMedication(payload) {
  return apiPost("/api/manual-medication-access/assess", payload);
}

export function confirmManualMedication(payload) {
  return apiPost("/api/manual-medication-access/confirm", payload);
}

export function loadDispenseRecords() {
  return apiGet("/api/dispense/records");
}
