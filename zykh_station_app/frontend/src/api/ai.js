import { apiPost } from "./client.js";

export function askAssistant(message) {
  return apiPost("/api/ai/chat", { message });
}
