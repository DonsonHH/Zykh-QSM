export const API_BASE = "";

export async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  const contentType = res.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await res.json() : {};
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || data.detail || `请求失败：${res.status}`);
  }
  return data;
}

export function formBody(data) {
  return {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(data).toString()
  };
}

export async function loadSnapshot() {
  const [statusRes, medRes, planRes, recordRes, vitalRes, profileRes] = await Promise.all([
    api("/api/status"),
    api("/api/medicines"),
    api("/api/plans"),
    api("/api/records"),
    api("/api/vitals"),
    api("/api/profile")
  ]);

  return {
    status: statusRes,
    medicines: medRes.medicines || [],
    plans: planRes.plans || [],
    records: recordRes.records || [],
    vitals: vitalRes.vitals || [],
    profile: profileRes.profile || {}
  };
}
