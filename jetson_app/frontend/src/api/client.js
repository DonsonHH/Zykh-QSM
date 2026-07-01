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

async function safeApi(path, fallback, timeoutMs = 5000) {
  let timer = null;
  try {
    const timeout = new Promise((resolve) => {
      timer = window.setTimeout(() => resolve(fallback), timeoutMs);
    });
    return await Promise.race([api(path), timeout]);
  } catch {
    return fallback;
  } finally {
    if (timer) window.clearTimeout(timer);
  }
}

export async function loadSnapshot() {
  const offlineStatus = {
    ok: true,
    jetson: {},
    qsm: {
      online: false,
      status: { ok: false, error: "QSM 状态检查超时" },
      adb: { ok: false, connected: false },
      forward: { ok: false }
    }
  };
  const [statusRes, medRes, planRes, recordRes, vitalRes, profileRes] = await Promise.all([
    safeApi("/api/status", offlineStatus, 2500),
    safeApi("/api/medicines", { medicines: [] }),
    safeApi("/api/plans", { plans: [] }),
    safeApi("/api/records", { records: [] }),
    safeApi("/api/vitals", { vitals: [] }),
    safeApi("/api/profile", { profile: {} })
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
