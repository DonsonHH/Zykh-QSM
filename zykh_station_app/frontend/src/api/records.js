import { apiGet, apiPost } from "./client.js";

export function loadRecordsSummary() {
  return apiGet("/api/records/summary");
}

export function loadRecentRecords() {
  return apiGet("/api/records/recent");
}

export function loadSyncStatus() {
  return apiGet("/api/sync/status");
}

export function runMockSync() {
  return apiPost("/api/sync/mock", {});
}
