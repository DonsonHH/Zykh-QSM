import { apiGet } from "./client.js";

export function loadDeviceCheck() {
  return apiGet("/api/device/check");
}
