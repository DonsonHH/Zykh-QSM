import { apiGet, apiPatch } from "./client.js";

export function loadBasicSettings() {
  return apiGet("/api/settings/basic");
}

export function saveBasicSettings(payload) {
  return apiPatch("/api/settings/basic", payload);
}
