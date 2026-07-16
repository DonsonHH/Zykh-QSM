import { apiGet } from "./client.js";
import { mockDashboard } from "./mockData.js";

export async function loadDashboard() {
  try {
    return await apiGet("/api/dashboard");
  } catch (error) {
    return { ...mockDashboard, offline: true, error: error.message };
  }
}
