const state = {
  medicines: [],
  plans: [],
  records: [],
};

const $ = (id) => document.getElementById(id);

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 2600);
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const data = await res.json();
  if (!data.ok) {
    throw new Error(data.error || data.detail || "请求失败");
  }
  return data;
}

function formBody(obj) {
  return new URLSearchParams(obj).toString();
}

async function loadStatus() {
  const data = await api("/api/status");
  $("osText").textContent = `${data.os} / ${data.arch}`;
  $("timeText").textContent = data.time;
  renderDevices(data.devices);
}

async function loadMedicines() {
  const data = await api("/api/medicines");
  state.medicines = data.medicines;
  renderSlots();
  renderSlotSelect();
}

async function loadPlans() {
  const data = await api("/api/plans");
  state.plans = data.plans;
  const body = $("plansBody");
  body.innerHTML = "";
  for (const plan of state.plans) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(plan.time)}</td>
      <td>${escapeHtml(plan.medicine_name)}</td>
      <td>${plan.slot || "-"}</td>
      <td>${escapeHtml(plan.amount)}</td>
      <td><span class="pill">${plan.enabled ? "待服用" : "停用"}</span></td>
    `;
    body.appendChild(tr);
  }
}

async function loadRecords() {
  const data = await api("/api/records");
  state.records = data.records;
  const body = $("recordsBody");
  body.innerHTML = "";
  for (const rec of state.records) {
    const resultClass = rec.result === "success" ? "status-success" : "status-failed";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(rec.created_at)}</td>
      <td>${escapeHtml(rec.medicine_name)}</td>
      <td>${rec.slot || "-"}</td>
      <td>${escapeHtml(rec.action)}</td>
      <td class="${resultClass}">${escapeHtml(rec.result)}</td>
      <td>${escapeHtml(rec.detail)}</td>
    `;
    body.appendChild(tr);
  }
}

function renderSlots() {
  const slots = $("slots");
  slots.innerHTML = "";
  for (let i = 1; i <= 23; i += 1) {
    const med = state.medicines.find((item) => Number(item.slot) === i);
    const div = document.createElement("div");
    const status = !med ? "空仓" : med.stock <= 0 ? "缺药" : med.stock <= 10 ? "药量低" : "正常";
    div.className = `slot ${!med ? "empty" : med.stock <= 10 ? "low" : ""}`;
    div.innerHTML = `<strong>${String(i).padStart(2, "0")}</strong><span>${status}</span>`;
    div.title = med ? `${med.name}，余量 ${med.stock}` : "未绑定药品";
    slots.appendChild(div);
  }
}

function renderSlotSelect() {
  const select = $("slotSelect");
  select.innerHTML = "";
  for (let i = 1; i <= 23; i += 1) {
    const med = state.medicines.find((item) => Number(item.slot) === i);
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = med ? `${i}号仓 - ${med.name}` : `${i}号仓 - 未绑定`;
    select.appendChild(opt);
  }
}

function renderDevices(devices) {
  const list = $("deviceList");
  list.innerHTML = "";
  for (const [name, values] of Object.entries(devices)) {
    const section = document.createElement("section");
    section.innerHTML = `
      <h3>${escapeHtml(name.toUpperCase())}</h3>
      <p>${values.length ? values.map(escapeHtml).join(" / ") : "未发现"}</p>
    `;
    list.appendChild(section);
  }
}

async function readVitals() {
  const data = await api("/api/vitals/read", { method: "POST" });
  $("tempText").textContent = data.vitals.temperature;
  $("hrText").textContent = data.vitals.heart_rate;
  $("spo2Text").textContent = data.vitals.spo2;
  showToast(`体征读取完成：${data.vitals.source}`);
}

async function recognize() {
  const data = await api("/api/recognize", { method: "POST" });
  $("recName").textContent = data.recognition.name;
  $("recConf").textContent = `${Math.round(data.recognition.confidence * 100)}%`;
  showToast(data.recognition.note);
}

async function dispense() {
  const slot = $("slotSelect").value;
  $("dispenseState").textContent = "执行中";
  const data = await api("/api/dispense", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: formBody({ slot }),
  });
  $("dispenseState").textContent = data.result === "success" ? "完成" : "失败";
  showToast(data.detail);
  await loadMedicines();
  await loadRecords();
}

async function addMedicine(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = Object.fromEntries(form.entries());
  const data = await api("/api/medicines", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: formBody(payload),
  });
  state.medicines = data.medicines;
  event.currentTarget.reset();
  renderSlots();
  renderSlotSelect();
  showToast("药品已保存");
}

async function setGpio(button) {
  const gpio = button.dataset.gpio;
  const value = button.dataset.value;
  await api("/api/gpio", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: formBody({ gpio, value }),
  });
  showToast(`GPIO${gpio} 已设置为 ${value}`);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

async function refreshAll() {
  await loadStatus();
  await loadMedicines();
  await loadPlans();
  await loadRecords();
}

document.addEventListener("DOMContentLoaded", async () => {
  $("refreshBtn").addEventListener("click", refreshAll);
  $("readVitalsBtn").addEventListener("click", readVitals);
  $("recognizeBtn").addEventListener("click", recognize);
  $("dispenseBtn").addEventListener("click", () => dispense().catch((err) => {
    $("dispenseState").textContent = "失败";
    showToast(err.message);
  }));
  $("medicineForm").addEventListener("submit", (event) => addMedicine(event).catch((err) => showToast(err.message)));
  document.querySelectorAll(".gpio-btn").forEach((button) => {
    button.addEventListener("click", () => setGpio(button).catch((err) => showToast(err.message)));
  });

  try {
    await refreshAll();
    await readVitals();
  } catch (err) {
    showToast(err.message);
  }
});
