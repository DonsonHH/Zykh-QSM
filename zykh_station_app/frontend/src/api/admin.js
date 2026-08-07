import { apiRequest } from "./client.js";

const TOKEN_KEY = "zykh.admin.session";

export function getAdminToken() {
  return window.sessionStorage.getItem(TOKEN_KEY) || "";
}

export function setAdminToken(token) {
  if (token) {
    window.sessionStorage.setItem(TOKEN_KEY, token);
  } else {
    window.sessionStorage.removeItem(TOKEN_KEY);
  }
}

function adminRequest(path, options = {}) {
  const token = getAdminToken();
  return apiRequest(path, {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${token}`
    }
  }).catch((error) => {
    if (/会话|管理员会话|401/.test(error.message || "")) {
      setAdminToken("");
    }
    throw error;
  });
}

export async function createAdminSession(pin) {
  const data = await apiRequest("/api/admin/session", { method: "POST", payload: { pin } });
  setAdminToken(data.token);
  return data;
}

export async function closeAdminSession() {
  try {
    return await adminRequest("/api/admin/session", { method: "DELETE" });
  } finally {
    setAdminToken("");
  }
}

export function loadAdminOverview() {
  return adminRequest("/api/admin/overview");
}

export function loadAdminNetwork() {
  return adminRequest("/api/admin/network");
}

export function updateAdminNetwork(payload) {
  return adminRequest("/api/admin/network", { method: "PATCH", payload });
}

export function loadAdminLogs(source = "backend") {
  return adminRequest(`/api/admin/logs?source=${encodeURIComponent(source)}`);
}

export function loadAdminInquiries(limit = 40) {
  return adminRequest(`/api/admin/inquiries?limit=${encodeURIComponent(limit)}`);
}

export function runAdminSystemAction(action, confirmation) {
  return adminRequest("/api/admin/system/action", { method: "POST", payload: { action, confirmation } });
}

export function loadAdminUsers() {
  return adminRequest("/api/admin/users");
}

export function createAdminUser(payload) {
  return adminRequest("/api/admin/users", { method: "POST", payload });
}

export function updateAdminUser(userId, payload) {
  return adminRequest(`/api/admin/users/${encodeURIComponent(userId)}`, { method: "PATCH", payload });
}

export function deleteAdminUser(userId, confirmation) {
  return adminRequest(`/api/admin/users/${encodeURIComponent(userId)}`, {
    method: "DELETE",
    payload: { confirmation }
  });
}

export function enrollAdminFace(userId) {
  return adminRequest(`/api/admin/users/${encodeURIComponent(userId)}/face`, { method: "POST", payload: {} });
}

export function removeAdminFace(userId, confirmation) {
  return adminRequest(`/api/admin/users/${encodeURIComponent(userId)}/face`, {
    method: "DELETE",
    payload: { confirmation }
  });
}

export function enrollAdminFingerprint(userId) {
  return adminRequest(`/api/admin/users/${encodeURIComponent(userId)}/fingerprint`, { method: "POST", payload: {} });
}

export function loadAdminFingerprintEnrollment(userId, jobId) {
  return adminRequest(
    `/api/admin/users/${encodeURIComponent(userId)}/fingerprint/${encodeURIComponent(jobId)}`
  );
}

export function removeAdminFingerprint(userId, confirmation) {
  return adminRequest(`/api/admin/users/${encodeURIComponent(userId)}/fingerprint`, {
    method: "DELETE",
    payload: { confirmation }
  });
}

export function loadAdminMedicines() {
  return adminRequest("/api/admin/medicines");
}

export function updateAdminMedicine(medicineId, payload) {
  return adminRequest(`/api/admin/medicines/${encodeURIComponent(medicineId)}`, { method: "PATCH", payload });
}

export function loadAdminTodayPlans() {
  return adminRequest("/api/admin/today-plans");
}

export function createAdminTodayPlan(payload) {
  return adminRequest("/api/admin/today-plans", { method: "POST", payload });
}

export function updateAdminTodayPlan(planId, payload) {
  return adminRequest(`/api/admin/today-plans/${encodeURIComponent(planId)}`, { method: "PATCH", payload });
}

export function deleteAdminTodayPlan(planId) {
  return adminRequest(`/api/admin/today-plans/${encodeURIComponent(planId)}`, {
    method: "DELETE",
    payload: { confirmation: "DELETE PLAN" }
  });
}

export function openAdminCabinet(slot, confirmation, reason = "管理员调试开柜") {
  return adminRequest(`/api/admin/cabinet/${slot}/open`, {
    method: "POST",
    payload: { confirmation, reason }
  });
}
