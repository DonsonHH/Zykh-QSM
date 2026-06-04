const $ = (id) => document.getElementById(id);

const state = {
  medicines: [],
  plans: [],
  records: [],
  nextPlan: null,
};

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || data.detail || "操作失败");
  return data;
}

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 2800);
}

function tickClock() {
  const now = new Date();
  const time = now.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  const date = now.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
  $("clockText").textContent = time;
  $("topClock").textContent = time;
  $("dateText").textContent = date;
  $("topDate").textContent = date;
  renderCountdown();
}

async function refreshData() {
  const [status, medicines, plans, records] = await Promise.all([
    api("/api/status"),
    api("/api/medicines"),
    api("/api/plans"),
    api("/api/records"),
  ]);

  state.medicines = medicines.medicines;
  state.plans = plans.plans;
  state.records = records.records;

  $("deviceText").textContent = `${status.hostname || "系统"} 已就绪，可以开始使用`;
  renderNextPlan();
  renderSlots();
}

function renderNextPlan() {
  const enabled = state.plans.filter((plan) => plan.enabled);
  state.nextPlan = enabled[0] || null;
  if (!state.nextPlan) {
    $("nextTime").textContent = "--:--";
    $("nextMedicine").textContent = "暂无用药计划";
    $("nextDose").textContent = "请进入管理设置添加";
    $("countdownText").textContent = "待设置";
    return;
  }
  $("nextTime").textContent = state.nextPlan.time;
  $("nextMedicine").textContent = state.nextPlan.medicine_name;
  $("nextDose").textContent = `${state.nextPlan.amount}  口服`;
  renderCountdown();
}

function renderCountdown() {
  if (!state.nextPlan || !$("countdownText")) return;
  const [hour, minute] = String(state.nextPlan.time || "00:00").split(":").map(Number);
  const now = new Date();
  const next = new Date(now);
  next.setHours(hour || 0, minute || 0, 0, 0);
  if (next < now) next.setDate(next.getDate() + 1);
  const diff = Math.max(0, next - now);
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  $("countdownText").textContent = `还有 ${h} 小时 ${m} 分钟`;
}

function renderSlots() {
  const slots = $("slots");
  slots.innerHTML = "";
  for (let i = 1; i <= 6; i += 1) {
    const med = state.medicines.find((item) => Number(item.slot) === i);
    const status = !med ? "空仓" : med.stock <= 0 ? "缺药" : med.stock <= 10 ? "药量低" : "正常";
    const div = document.createElement("div");
    div.className = `slot ${!med ? "empty" : med.stock <= 10 ? "low" : ""}`;
    div.innerHTML = `<strong>${String(i).padStart(2, "0")}</strong><span>${status}</span>`;
    div.title = med ? `${med.name}，余量 ${med.stock}` : "未绑定药品";
    slots.appendChild(div);
  }
  const normal = countSlots("normal");
  const low = countSlots("low");
  const empty = 23 - state.medicines.filter((item) => Number(item.slot) >= 1 && Number(item.slot) <= 23).length;
  const head = document.querySelector(".slots-head span");
  if (head) head.textContent = `共23仓 / 正常${normal} / 低${low} / 空${empty}`;
}

function countSlots(type) {
  let count = 0;
  for (let i = 1; i <= 23; i += 1) {
    const med = state.medicines.find((item) => Number(item.slot) === i);
    if (type === "normal" && med && med.stock > 10) count += 1;
    if (type === "low" && med && med.stock > 0 && med.stock <= 10) count += 1;
  }
  return count;
}

async function dispenseNext() {
  if (!state.nextPlan) {
    showToast("当前没有可执行的用药计划");
    return;
  }
  $("voiceText").textContent = `正在从 ${state.nextPlan.slot} 号药仓取出 ${state.nextPlan.medicine_name}`;
  const body = new URLSearchParams({ slot: state.nextPlan.slot }).toString();
  const data = await api("/api/dispense", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  showToast(data.detail || "取药完成");
  $("voiceText").textContent = "取药完成，请核对药品后服用";
  await refreshData();
}

async function readVitals() {
  const data = await api("/api/vitals/read", { method: "POST" });
  const v = data.vitals;
  $("vitalsText").textContent = `体温 ${v.temperature}℃ / 心率 ${v.heart_rate} / 血氧 ${v.spo2}%`;
  $("voiceText").textContent = "体征测量完成，数据已写入健康档案记忆";
  showToast("体征测量完成，AI 问诊可调用");
}

async function captureAndRecognize() {
  $("recognitionText").textContent = "正在拍照识别...";
  const capture = await api("/api/camera/capture", { method: "POST" });
  const code = await detectBarcodeFromImage(capture.image_url);
  if (code) {
    const body = new URLSearchParams({ code }).toString();
    const data = await api("/api/medicine/auto_add", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    if (data.found) {
      $("recognitionText").textContent = `${data.medicine.name} 已录入 ${data.slot}号仓`;
      $("voiceText").textContent = `识别到 ${data.medicine.name}，有效期 ${data.medicine.expire_date || "未填写"}`;
      showToast(`条码 ${code} 已自动录入`);
      await refreshData();
      return;
    }
    $("recognitionText").textContent = `识别到条码 ${code}，本地目录未收录`;
    showToast("请在管理设置中补充该药品信息");
    return;
  }

  const recog = await api("/api/recognize", { method: "POST" });
  $("recognitionText").textContent = `${recog.recognition.name}（${Math.round(recog.recognition.confidence * 100)}%）`;
  $("voiceText").textContent = "未识别到条码，已使用图像识别演示结果";
}

async function detectBarcodeFromImage(imageUrl) {
  if (!("BarcodeDetector" in window)) {
    showToast("当前浏览器不支持条码识别，后续可接 zbar/RKNN");
    return "";
  }
  const detector = new BarcodeDetector({
    formats: ["qr_code", "ean_13", "ean_8", "code_128", "data_matrix"],
  });
  const img = new Image();
  img.src = `${imageUrl}?t=${Date.now()}`;
  await img.decode();
  const codes = await detector.detect(img);
  return codes[0]?.rawValue || "";
}

document.addEventListener("DOMContentLoaded", async () => {
  tickClock();
  setInterval(tickClock, 1000);

  $("dispenseBtn").addEventListener("click", () => dispenseNext().catch((err) => showToast(err.message)));
  $("readVitalsBtn").addEventListener("click", () => readVitals().catch((err) => showToast(err.message)));
  $("captureBtn").addEventListener("click", () => captureAndRecognize().catch((err) => showToast(err.message)));

  try {
    await refreshData();
  } catch (err) {
    showToast(err.message);
  }
});
