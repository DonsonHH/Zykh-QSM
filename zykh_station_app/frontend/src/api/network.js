import { apiGet, apiPost } from "./client.js";

export function loadNetworkStatus() {
  return apiGet("/api/network/status");
}

export function setNetworkMode(mode) {
  return apiPost("/api/network/mode", { mode });
}

export function startQsm4g() {
  return apiPost("/api/network/start-4g", {});
}
