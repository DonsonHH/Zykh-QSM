const $ = (id) => document.getElementById(id);

let lastReply = "";
let recognition = null;
let listening = false;
const decoder = new TextDecoder("utf-8");

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
  if (!data.ok) throw new Error(data.error || data.detail || "操作失败");
  return data;
}

function addMessage(role, text) {
  const article = document.createElement("article");
  article.className = `msg ${role}`;
  const avatarClass = role === "user" ? "msg-avatar user-avatar" : "msg-avatar bot-avatar";
  const content = role === "assistant" ? renderMarkdown(text) : `<p>${escapeHtml(text)}</p>`;
  article.innerHTML = `<div class="${avatarClass}"></div><div class="bubble markdown-body">${content}<time>${timeText()}</time></div>`;
  $("messages").appendChild(article);
  scrollMessages();
  return article;
}

function scrollMessages() {
  $("messages").scrollTop = $("messages").scrollHeight;
}

function setStreamState(text) {
  $("streamState").textContent = text;
}

function tickClock() {
  const now = new Date();
  $("dateText").textContent = now.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).replace(/\//g, "-");
  $("clockText").textContent = now.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function timeText() {
  return new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function speak(text) {
  if (!("speechSynthesis" in window)) {
    showToast("当前浏览器不支持语音播报");
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 0.95;
  utterance.pitch = 1;
  window.speechSynthesis.speak(utterance);
}

async function loadContext() {
  const [profileRes, vitalsRes, medicineRes] = await Promise.all([
    api("/api/profile"),
    api("/api/vitals"),
    api("/api/medicines"),
  ]);
  renderProfile(profileRes.profile);
  renderVitals(vitalsRes.vitals);
  renderMedicines(medicineRes.medicines);
}

function renderProfile(profile) {
  $("profileName").value = profile.name || "";
  $("profileGender").value = profile.gender || "";
  $("profileAge").value = profile.age || "";
  $("profileHeight").value = profile.height || "";
  $("profileWeight").value = profile.weight || "";
  $("profileConditions").value = profile.conditions || "";
  $("profileAllergies").value = profile.allergies || "";
  $("profileNotes").value = profile.notes || "";
  $("profileGenderText").textContent = profile.gender || "未填";
  $("profileAgeText").textContent = profile.age ? `${profile.age} 岁` : "未填";
  $("profileTime").textContent = profile.updated_at ? profile.updated_at.slice(11, 16) : "--";
  $("contextName").textContent = "智药康护 AI 助手";
}

function renderVitals(vitals) {
  const list = $("vitalsList");
  list.innerHTML = "";
  const latest = vitals.slice(0, 4);
  if (!latest.length) {
    list.innerHTML = "<li>暂无体征记录</li>";
    $("lastTemp").textContent = "-- ℃";
    $("lastHr").textContent = "-- 次/分";
    $("lastSpo2").textContent = "-- %";
    return;
  }
  const first = latest[0];
  $("lastTemp").textContent = `${first.temperature || "--"} ℃`;
  $("lastHr").textContent = `${first.heart_rate || "--"} 次/分`;
  $("lastSpo2").textContent = `${first.spo2 || "--"} %`;
  $("profileTime").textContent = first.created_at ? first.created_at.slice(11, 16) : "--";
  for (const item of latest) {
    const li = document.createElement("li");
    li.innerHTML = `<span>${escapeHtml((item.created_at || "").slice(5, 16))}</span><b>${item.systolic || "--"}/${item.diastolic || "--"}</b>`;
    list.appendChild(li);
  }
}

function renderMedicines(medicines) {
  const list = $("medicineList");
  list.innerHTML = "";
  for (const med of medicines.slice(0, 5)) {
    const li = document.createElement("li");
    li.innerHTML = `<span>${escapeHtml(med.name)}</span><b>${escapeHtml(med.stock)} 片</b>`;
    list.appendChild(li);
  }
}

async function saveProfile() {
  const body = new URLSearchParams({
    name: $("profileName").value.trim(),
    gender: $("profileGender").value.trim(),
    age: $("profileAge").value.trim(),
    height: $("profileHeight").value.trim(),
    weight: $("profileWeight").value.trim(),
    conditions: $("profileConditions").value.trim(),
    allergies: $("profileAllergies").value.trim(),
    notes: $("profileNotes").value.trim(),
  }).toString();
  const data = await api("/api/profile", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  renderProfile(data.profile);
  showToast("老人档案已保存");
}

async function saveVitals(source = "manual") {
  const body = new URLSearchParams({
    temperature: $("vitalTemp").value.trim(),
    heart_rate: $("vitalHr").value.trim(),
    spo2: $("vitalSpo2").value.trim(),
    systolic: $("vitalSys").value.trim(),
    diastolic: $("vitalDia").value.trim(),
    source,
  }).toString();
  const data = await api("/api/vitals", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  renderVitals(data.vitals);
  showToast("体征已记录");
}

async function readVitals() {
  const data = await api("/api/vitals/read", { method: "POST" });
  const v = data.vitals;
  $("vitalTemp").value = v.temperature;
  $("vitalHr").value = v.heart_rate;
  $("vitalSpo2").value = v.spo2;
  $("vitalSys").value = v.systolic || "";
  $("vitalDia").value = v.diastolic || "";
  const vitalsRes = await api("/api/vitals");
  renderVitals(vitalsRes.vitals);
  showToast("已读取并记录体征");
}

async function sendMessage() {
  const input = $("messageInput");
  const text = input.value.trim();
  if (!text) {
    showToast("请先输入或语音说出问题");
    return;
  }

  input.value = "";
  updateCharCount();
  addMessage("user", text);
  const pending = addMessage("assistant", "");
  pending.classList.add("streaming");
  const bubble = pending.querySelector(".bubble");
  lastReply = "";
  setStreamState("生成中");

  const body = new URLSearchParams({ message: text }).toString();
  try {
    const res = await fetch("/api/ai/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
    if (!res.body) {
      await sendMessageFallback(text, pending);
      return;
    }
    await readSseStream(res.body, {
      onDelta(delta) {
        lastReply += delta;
        bubble.innerHTML = `${renderMarkdown(lastReply)}<time>${timeText()}</time>`;
        scrollMessages();
      },
      onError(message) {
        bubble.innerHTML = `${escapeHtml(message || "AI 问诊请求失败")}<time>${timeText()}</time>`;
        showToast(message || "AI 问诊请求失败");
      },
    });
    if (lastReply) speak(lastReply);
  } catch (err) {
    await sendMessageFallback(text, pending).catch(() => {
      bubble.innerHTML = `${escapeHtml(err.message)}<time>${timeText()}</time>`;
      showToast(err.message);
    });
  } finally {
    pending.classList.remove("streaming");
    setStreamState("本地在线");
  }
}

async function sendMessageFallback(text, pending) {
  const bubble = pending.querySelector(".bubble");
  const body = new URLSearchParams({ message: text }).toString();
  const res = await fetch("/api/ai/chat", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "AI 问诊请求失败");
  lastReply = data.reply || "";
  bubble.innerHTML = `${renderMarkdown(lastReply)}<time>${timeText()}</time>`;
  if (lastReply) speak(lastReply);
}

async function readSseStream(body, handlers) {
  const reader = body.getReader();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const event = parseSseEvent(raw);
      if (!event.data) continue;
      const payload = JSON.parse(event.data);
      if (event.event === "delta") handlers.onDelta(payload.delta || "");
      if (event.event === "error") handlers.onError(payload.error || payload.detail || "AI 请求失败");
    }
  }
}

function parseSseEvent(raw) {
  const event = { event: "message", data: "" };
  for (const line of raw.split(/\r?\n/)) {
    if (line.startsWith("event:")) event.event = line.slice(6).trim();
    if (line.startsWith("data:")) event.data += line.slice(5).trim();
  }
  return event;
}

function setupSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    $("micBtn").textContent = "不支持语音";
    $("micBtn").disabled = true;
    return;
  }
  recognition = new SpeechRecognition();
  recognition.lang = "zh-CN";
  recognition.continuous = false;
  recognition.interimResults = true;

  recognition.onstart = () => {
    listening = true;
    $("micBtn").textContent = "正在听";
  };
  recognition.onend = () => {
    listening = false;
    $("micBtn").textContent = "点击说话";
  };
  recognition.onerror = (event) => showToast(`语音输入失败：${event.error}`);
  recognition.onresult = (event) => {
    let text = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) text += event.results[i][0].transcript;
    $("messageInput").value = text;
    updateCharCount();
    const last = event.results[event.results.length - 1];
    if (last && last.isFinal) setTimeout(() => sendMessage().catch((err) => showToast(err.message)), 200);
  };
}

function renderMarkdown(text) {
  const safe = escapeHtml(text || "");
  const lines = safe.split(/\r?\n/);
  const html = [];
  let listType = "";
  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`);
      listType = "";
    }
  };
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      closeList();
      continue;
    }
    if (/^###\s+/.test(line)) {
      closeList();
      html.push(`<h3>${inlineMarkdown(line.replace(/^###\s+/, ""))}</h3>`);
    } else if (/^\d+\.\s+/.test(line)) {
      if (listType !== "ol") {
        closeList();
        html.push("<ol>");
        listType = "ol";
      }
      html.push(`<li>${inlineMarkdown(line.replace(/^\d+\.\s+/, ""))}</li>`);
    } else if (/^[-*]\s+/.test(line)) {
      if (listType !== "ul") {
        closeList();
        html.push("<ul>");
        listType = "ul";
      }
      html.push(`<li>${inlineMarkdown(line.replace(/^[-*]\s+/, ""))}</li>`);
    } else {
      closeList();
      html.push(`<p>${inlineMarkdown(line)}</p>`);
    }
  }
  closeList();
  return html.join("");
}

function inlineMarkdown(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function updateCharCount() {
  $("charCount").textContent = String($("messageInput").value.length);
}

function toggleMic() {
  if (!recognition) return;
  if (listening) recognition.stop();
  else recognition.start();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

document.addEventListener("DOMContentLoaded", async () => {
  tickClock();
  setInterval(tickClock, 1000);
  setupSpeechRecognition();
  $("micBtn").addEventListener("click", toggleMic);
  $("sendBtn").addEventListener("click", () => sendMessage().catch((err) => showToast(err.message)));
  $("saveProfileBtn").addEventListener("click", () => saveProfile().catch((err) => showToast(err.message)));
  $("saveVitalsBtn").addEventListener("click", () => saveVitals().catch((err) => showToast(err.message)));
  $("readVitalsBtn").addEventListener("click", () => readVitals().catch((err) => showToast(err.message)));
  $("speakLastBtn").addEventListener("click", () => lastReply ? speak(lastReply) : showToast("还没有可播报的回答"));
  document.querySelectorAll("[data-question]").forEach((btn) => {
    btn.addEventListener("click", () => {
      $("messageInput").value = btn.dataset.question;
      updateCharCount();
      $("messageInput").focus();
    });
  });
  $("messageInput").addEventListener("input", updateCharCount);
  try {
    await loadContext();
  } catch (err) {
    showToast(err.message);
  }
});
