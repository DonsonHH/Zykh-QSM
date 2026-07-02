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

const demoMedicines = [
  { slot: 1, name: "阿司匹林肠溶片", dosage: "100mg", stock: 36, unit: "盒", category: "慢病常用", indication_tags: "头痛发热、关节疼痛", contraindications: "对阿司匹林过敏者禁用", expire_date: "2027-12-31", is_emergency: 1 },
  { slot: 2, name: "硝苯地平控释片", dosage: "30mg", stock: 24, unit: "盒", category: "慢病常用", indication_tags: "高血压随访", contraindications: "低血压或过敏禁用", expire_date: "2027-09-30", is_emergency: 0 },
  { slot: 3, name: "布洛芬缓释胶囊", dosage: "200mg", stock: 28, unit: "盒", category: "感冒发热", indication_tags: "发热、疼痛", contraindications: "胃溃疡、NSAID过敏禁用", expire_date: "2027-08-31", is_emergency: 1 },
  { slot: 4, name: "连花清瘟胶囊", dosage: "0.35g*24粒", stock: 18, unit: "盒", category: "感冒发热", indication_tags: "咽痛、流涕、感冒", contraindications: "孕妇、过敏体质需咨询医生", expire_date: "2027-08-31", is_emergency: 1 },
  { slot: 5, name: "蒙脱石散", dosage: "3g", stock: 20, unit: "袋", category: "肠胃", indication_tags: "腹泻、肠胃不适", contraindications: "高热、便血、严重脱水需就医", expire_date: "2027-03-31", is_emergency: 1 },
  { slot: 6, name: "氯雷他定片", dosage: "10mg", stock: 16, unit: "盒", category: "过敏", indication_tags: "皮肤瘙痒、过敏性鼻炎", contraindications: "呼吸困难或面唇肿胀需救援", expire_date: "2027-01-31", is_emergency: 1 },
  { slot: 10, name: "碘伏棉签", dosage: "10支/盒", stock: 16, unit: "盒", category: "外伤消毒", indication_tags: "擦伤、外伤消毒", contraindications: "碘过敏慎用", expire_date: "2027-02-28", is_emergency: 1 },
  { slot: 11, name: "创可贴", dosage: "20片/盒", stock: 25, unit: "盒", category: "外伤消毒", indication_tags: "轻微擦伤、伤口保护", contraindications: "大面积伤口需医生处理", expire_date: "2027-06-30", is_emergency: 1 }
];

const demoPlans = [
  { id: "demo-1", slot: 1, time: "08:00", amount: "1片", medicine_name: "阿司匹林肠溶片", enabled: 1 },
  { id: "demo-2", slot: 2, time: "18:30", amount: "1片", medicine_name: "硝苯地平控释片", enabled: 1 },
  { id: "demo-3", slot: 5, time: "20:00", amount: "1袋", medicine_name: "蒙脱石散", enabled: 1 }
];

const demoRecords = [
  { id: "r1", created_at: "21:08", action: "体征读取", subject: "张三", result: "已同步", detail: "体温 36.6℃，血压 128/82mmHg" },
  { id: "r2", created_at: "20:35", action: "AI问询", subject: "李四", result: "已同步", detail: "咨询关于降糖药用法" },
  { id: "r3", created_at: "19:42", action: "药品扫码", subject: "阿司匹林肠溶片", result: "待同步", detail: "100mg × 28片" },
  { id: "r4", created_at: "18:50", action: "用药发放", subject: "张三", result: "已同步", detail: "阿司匹林肠溶片 100mg" }
];

const demoVitals = [{ id: "v1", temperature: 35.7, heart_rate: 72, spo2: 98, systolic: 128, diastolic: 82, created_at: "21:08" }];

const demoAdminLogs = {
  emergency_sessions: [
    { id: "e1", created_at: "20:35", risk_level: "medium", symptoms_summary: "李四咨询降糖药用法", need_admin_review: 1, action_summary: "需要值守员复核" },
    { id: "e2", created_at: "17:36", risk_level: "low", symptoms_summary: "王五咨询胃痛缓解方法", need_admin_review: 0, action_summary: "低风险已记录" }
  ],
  dispense_records: [
    { id: "d1", created_at: "18:50", medicine_name: "阿司匹林肠溶片", slot: 1, dry_run: 1, success: 1 }
  ],
  network_events: [],
  operator_logs: [],
  pending_sync_count: 12
};

export async function loadSnapshot() {
  const offlineStatus = {
    ok: true,
    qsm_main: {},
    site: {
      station_name: "偏远社区康护站",
      station_type: "village",
      location_name: "村镇智慧用药服务点",
      network_mode: "weak",
      ai_mode: "rules",
      sync_status: "待同步"
    },
    network: {
      mode: "weak",
      ai_mode: "rules",
      last_sync_at: "",
      pending_sync_count: 0,
      sync_status: "待同步"
    },
    qsm: {
      online: false,
      status: { ok: false, error: "外设采集与执行控制平台状态检查超时" },
      adb: { ok: false, connected: false },
      forward: { ok: false }
    }
  };
  const [statusRes, siteRes, medRes, planRes, recordRes, vitalRes, profileRes, logRes] = await Promise.all([
    safeApi("/api/status", offlineStatus, 2500),
    safeApi("/api/site", { site: offlineStatus.site }),
    safeApi("/api/medicines", { medicines: [] }),
    safeApi("/api/plans", { plans: [] }),
    safeApi("/api/records", { records: [] }),
    safeApi("/api/vitals", { vitals: [] }),
    safeApi("/api/profile", { profile: {} }),
    safeApi("/api/admin/logs", { emergency_sessions: [], dispense_records: [], network_events: [], operator_logs: [], pending_sync_count: 0 })
  ]);

  const medicines = medRes.medicines || [];
  const hasStock = medicines.some((item) => Number(item.stock) > 0);
  const plans = planRes.plans || [];
  const records = recordRes.records || [];
  const vitals = vitalRes.vitals || [];
  const adminLogs = logRes || {};

  return {
    status: statusRes,
    site: siteRes.site || statusRes.site || offlineStatus.site,
    adminLogs: hasStock ? adminLogs : demoAdminLogs,
    medicines: hasStock ? medicines : demoMedicines,
    plans: plans.length ? plans : demoPlans,
    records: records.length ? records : demoRecords,
    vitals: vitals.length ? vitals : demoVitals,
    profile: profileRes.profile?.name ? profileRes.profile : { name: "张三", age: 65, gender: "男", conditions: "高血压；糖尿病前期", allergies: "青霉素" }
  };
}
