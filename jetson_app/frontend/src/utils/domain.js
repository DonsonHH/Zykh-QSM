export const slotLayout = [
  ...Array.from({ length: 8 }, (_, i) => ({ slot: i + 1, kind: "big", label: "大仓" })),
  ...Array.from({ length: 9 }, (_, i) => ({ slot: i + 9, kind: "small", label: "小仓" })),
  ...Array.from({ length: 6 }, (_, i) => ({ slot: i + 18, kind: "medium", label: "中仓" }))
];

export function slotKind(slot) {
  const item = slotLayout.find((entry) => entry.slot === Number(slot));
  return item?.kind || "medium";
}

export function slotLabel(slot) {
  const item = slotLayout.find((entry) => entry.slot === Number(slot));
  return item?.label || "中仓";
}

export function stockState(stock) {
  const value = Number(stock || 0);
  if (value <= 0) return "empty";
  if (value <= 5) return "danger";
  if (value <= 12) return "warn";
  return "good";
}

export function stockText(stock) {
  const value = Number(stock || 0);
  return value > 0 ? `${value}` : "空仓";
}

export function medicineForSlot(medicines, slot) {
  return medicines.find((item) => Number(item.slot) === Number(slot)) || {};
}

export function latestVitals(vitals) {
  return vitals[0] || {};
}

export function enabledPlans(plans) {
  return plans.filter((plan) => Number(plan.enabled) !== 0);
}

export function nextPlan(plans) {
  return enabledPlans(plans)[0] || null;
}

export function formatClock(date) {
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export function formatDay(date) {
  return date.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "long"
  });
}
