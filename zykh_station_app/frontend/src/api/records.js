import { apiDelete, apiGet, apiPatch, apiPost } from "./client.js";

export function loadRecordsSummary() {
  return apiGet("/api/records/summary");
}

export function loadRecentRecords() {
  return apiGet("/api/records/recent");
}

export function loadSyncStatus() {
  return apiGet("/api/sync/status");
}

export function runSync() {
  return apiPost("/api/sync/run", {});
}

export function loadServiceUsers() {
  return apiGet("/api/records/service-users");
}

export function createServiceUser(payload) {
  return apiPost("/api/records/service-users", payload);
}

export function updateServiceUser(userId, payload) {
  return apiPatch(`/api/records/service-users/${userId}`, payload);
}

export function deleteServiceUser(userId) {
  return apiDelete(`/api/records/service-users/${userId}`);
}

export function loadTodayPlans() {
  return apiGet("/api/records/today-plans");
}
