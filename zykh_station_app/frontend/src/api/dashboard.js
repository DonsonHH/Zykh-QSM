import { apiGet } from "./client.js";
import { mockDashboard } from "./mockData.js";

export async function loadDashboard(targetUser = "") {
  try {
    const query = targetUser ? `?target_user=${encodeURIComponent(targetUser)}` : "";
    return await apiGet(`/api/dashboard${query}`);
  } catch (error) {
    return { ...mockDashboard, offline: true, error: error.message };
  }
}
