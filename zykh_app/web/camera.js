const $ = (id) => document.getElementById(id);
let running = true;

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 2400);
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || data.detail || "操作失败");
  return data;
}

function startLoop() {
  running = true;
  $("statusText").textContent = "实时预览中，请将药品放在识别框内";
  $("liveImage").src = `/api/camera/stream?width=640&height=480&fps=30&t=${Date.now()}`;
}

function pauseLoop() {
  running = false;
  $("statusText").textContent = "预览已暂停";
  $("liveImage").removeAttribute("src");
  fetch("/api/camera/stream/stop", { method: "POST", keepalive: true }).catch(() => {});
}

async function recognizeCurrent() {
  pauseLoop();
  $("statusText").textContent = "正在识别药品...";
  await new Promise((resolve) => setTimeout(resolve, 600));
  const capture = await api("/api/camera/capture", { method: "POST" });
  $("liveImage").src = `${capture.image_url}?t=${Date.now()}`;
  const recog = await api("/api/recognize", { method: "POST" });
  $("resultText").textContent = `${recog.recognition.name}（${Math.round(recog.recognition.confidence * 100)}%）`;
  $("statusText").textContent = "识别完成，请核对结果";
  showToast("识别完成");
}

document.addEventListener("DOMContentLoaded", () => {
  $("pauseBtn").addEventListener("click", pauseLoop);
  $("resumeBtn").addEventListener("click", startLoop);
  $("captureBtn").addEventListener("click", () => recognizeCurrent().catch((err) => showToast(err.message)));
  startLoop();
});
