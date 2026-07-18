import { apiGet, apiPost } from "./client.js";

export function evaluateInquiry(payload) {
  return apiPost("/api/inquiry/evaluate", payload);
}

export function loadInquiryRecords() {
  return apiGet("/api/inquiry/records");
}

export function createInquirySession(payload) {
  return apiPost("/api/inquiry/sessions", payload);
}

export function loadInquirySessions() {
  return apiGet("/api/inquiry/sessions");
}

export function loadInquirySession(sessionId) {
  return apiGet(`/api/inquiry/sessions/${encodeURIComponent(sessionId)}`);
}

export function sendInquiryTurn(sessionId, transcript) {
  return apiPost(`/api/inquiry/sessions/${encodeURIComponent(sessionId)}/turn`, { transcript });
}

export function attachInquiryVitals(sessionId, payload) {
  return apiPost(`/api/inquiry/sessions/${encodeURIComponent(sessionId)}/vitals`, payload);
}
