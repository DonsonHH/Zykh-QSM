import { apiGet, apiPost } from "./client.js";

export function confirmDispense(payload) {
  return apiPost("/api/dispense/confirm", payload);
}

export function loadDispenseRecords() {
  return apiGet("/api/dispense/records");
}
