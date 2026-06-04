const $ = (id) => document.getElementById(id);

const layout = [
  { slot: 1, size: "big", label: "大仓", spec: "100 x 100 mm", grid: "1 / 1 / 3 / 2" },
  { slot: 2, size: "big", label: "大仓", spec: "100 x 100 mm", grid: "1 / 2 / 3 / 3" },
  { slot: 3, size: "big", label: "大仓", spec: "100 x 100 mm", grid: "3 / 1 / 5 / 2" },
  { slot: 4, size: "big", label: "大仓", spec: "100 x 100 mm", grid: "3 / 2 / 5 / 3" },
  { slot: 5, size: "big", label: "大仓", spec: "100 x 100 mm", grid: "5 / 1 / 7 / 2" },
  { slot: 6, size: "big", label: "大仓", spec: "100 x 100 mm", grid: "5 / 2 / 7 / 3" },
  { slot: 7, size: "big", label: "大仓", spec: "100 x 100 mm", grid: "7 / 1 / 9 / 2" },
  { slot: 8, size: "big", label: "大仓", spec: "100 x 100 mm", grid: "7 / 2 / 9 / 3" },
  { slot: 9, size: "small", label: "小仓", spec: "65 x 65 mm", grid: "1 / 3 / 2 / 5" },
  { slot: 10, size: "small", label: "小仓", spec: "65 x 65 mm", grid: "1 / 5 / 2 / 7" },
  { slot: 11, size: "small", label: "小仓", spec: "65 x 65 mm", grid: "1 / 7 / 2 / 9" },
  { slot: 12, size: "small", label: "小仓", spec: "65 x 65 mm", grid: "2 / 3 / 3 / 5" },
  { slot: 13, size: "small", label: "小仓", spec: "65 x 65 mm", grid: "2 / 5 / 3 / 7" },
  { slot: 14, size: "small", label: "小仓", spec: "65 x 65 mm", grid: "2 / 7 / 3 / 9" },
  { slot: 15, size: "small", label: "小仓", spec: "65 x 65 mm", grid: "3 / 3 / 4 / 5" },
  { slot: 16, size: "small", label: "小仓", spec: "65 x 65 mm", grid: "3 / 5 / 4 / 7" },
  { slot: 17, size: "small", label: "小仓", spec: "65 x 65 mm", grid: "3 / 7 / 4 / 9" },
  { slot: 18, size: "medium", label: "中仓", spec: "100 x 65 mm", grid: "4 / 3 / 5 / 6" },
  { slot: 19, size: "medium", label: "中仓", spec: "100 x 65 mm", grid: "4 / 6 / 5 / 9" },
  { slot: 20, size: "medium", label: "中仓", spec: "100 x 65 mm", grid: "5 / 3 / 6 / 6" },
  { slot: 21, size: "medium", label: "中仓", spec: "100 x 65 mm", grid: "5 / 6 / 6 / 9" },
  { slot: 22, size: "medium", label: "中仓", spec: "100 x 65 mm", grid: "6 / 3 / 7 / 6" },
  { slot: 23, size: "medium", label: "中仓", spec: "100 x 65 mm", grid: "6 / 6 / 7 / 9" },
];

let medicines = [];

async function api(path) {
  const res = await fetch(path);
  const data = await res.json();
  if (!data.ok) throw new Error(data.error || "读取失败");
  return data;
}

function statusFor(med) {
  if (!med) return { text: "空仓", cls: "empty" };
  if (med.stock <= 0) return { text: "缺药", cls: "empty" };
  if (med.stock <= 10) return { text: "药量低", cls: "low" };
  return { text: "正常", cls: "normal" };
}

function renderBoard() {
  const board = $("cabinetBoard");
  board.innerHTML = "";
  for (const item of layout) {
    const med = medicines.find((m) => Number(m.slot) === item.slot);
    const status = statusFor(med);
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = `slot-cell ${item.size} ${status.cls}`;
    cell.style.gridArea = item.grid;
    cell.dataset.slot = item.slot;
    const compact = item.size !== "big";
    cell.innerHTML = compact ? `
      <strong>${String(item.slot).padStart(2, "0")}</strong>
      <b>${item.label}</b>
      <em>${status.text}</em>
    ` : `
      <strong>${String(item.slot).padStart(2, "0")}</strong>
      <b>${escapeHtml(med?.name || item.label)}</b>
      <span>${item.spec}</span>
      <em>${status.text}</em>
    `;
    cell.addEventListener("click", () => showDetail(item, med, cell));
    board.appendChild(cell);
  }
  const normal = medicines.filter((m) => m.stock > 10).length;
  const low = medicines.filter((m) => m.stock > 0 && m.stock <= 10).length;
  const empty = 23 - medicines.filter((m) => Number(m.slot) >= 1 && Number(m.slot) <= 23).length;
  $("summaryText").textContent = `正常 ${normal} / 低 ${low} / 空 ${empty}`;
}

function showDetail(item, med, cell) {
  document.querySelectorAll(".slot-cell").forEach((el) => el.classList.remove("selected"));
  cell.classList.add("selected");
  const status = statusFor(med);
  $("detailPanel").innerHTML = `
    <h2>${String(item.slot).padStart(2, "0")} 号${item.label}</h2>
    <p>${item.spec}，当前状态：${status.text}</p>
    <dl>
      <div><dt>药品</dt><dd>${escapeHtml(med?.name || "未绑定")}</dd></div>
      <div><dt>规格</dt><dd>${escapeHtml(med?.dosage || "--")}</dd></div>
      <div><dt>余量</dt><dd>${med ? `${med.stock} 片` : "--"}</dd></div>
      <div><dt>有效期</dt><dd>${escapeHtml(med?.expire_date || "--")}</dd></div>
      <div><dt>仓型</dt><dd>${item.label}</dd></div>
    </dl>
  `;
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
  try {
    const data = await api("/api/medicines");
    medicines = data.medicines || [];
    renderBoard();
  } catch (err) {
    $("summaryText").textContent = err.message;
  }
});
