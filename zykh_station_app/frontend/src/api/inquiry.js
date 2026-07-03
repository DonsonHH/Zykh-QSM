import { apiGet, apiPost } from "./client.js";

export function evaluateInquiry(payload) {
  return apiPost("/api/inquiry/evaluate", payload);
}

export function loadInquiryRecords() {
  return apiGet("/api/inquiry/records");
}
