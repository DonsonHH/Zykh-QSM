import { apiGet, apiPost } from "./client.js";

export function loadIdentityStatus() {
  return apiGet("/api/identity/status");
}

export function resolveIdentity() {
  return apiPost("/api/identity/resolve", {});
}

export function verifyDispenseIdentity(samples = 18) {
  return apiPost(`/api/identity/verify-dispense?samples=${samples}`, {});
}

export function enrollIdentity(userId, samples = 18) {
  return apiPost(`/api/identity/enroll/${encodeURIComponent(userId)}?samples=${samples}`, {});
}
