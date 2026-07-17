function clockMinutes(value) {
  const match = String(value || "").match(/^([01]\d|2[0-3]):([0-5]\d)$/);
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}

function localDateKey(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function planDateKey(plan) {
  if (plan.scheduled_at) return localDateKey(plan.scheduled_at);
  return /^\d{4}-\d{2}-\d{2}$/.test(plan.next_due_date || "") ? plan.next_due_date : "";
}

function calendarDayDifference(dateKey, reference) {
  if (!dateKey) return 0;
  const [year, month, day] = dateKey.split("-").map(Number);
  const referenceKey = localDateKey(reference);
  const [referenceYear, referenceMonth, referenceDay] = referenceKey.split("-").map(Number);
  return Math.round(
    (Date.UTC(year, month - 1, day) - Date.UTC(referenceYear, referenceMonth - 1, referenceDay)) / 86_400_000
  );
}

export function isMedicationPlanCompleted(plan) {
  return ["已执行", "已取出"].includes(String(plan?.status || ""));
}

export function medicationPlanDayLabel(plan, reference = new Date()) {
  const dateKey = planDateKey(plan || {});
  const difference = calendarDayDifference(dateKey, reference);
  if (difference === 1) return "次日";
  if (difference === 0 || !dateKey) return "";
  const [, month, day] = dateKey.split("-").map(Number);
  return `${month}月${day}日`;
}

export function medicationPlanTimeLabel(plan, reference = new Date()) {
  const time = plan.time || plan.timing_label || plan.schedule_label || "不限时";
  const dayLabel = medicationPlanDayLabel(plan, reference);
  return dayLabel ? `${dayLabel} ${time}` : time;
}

function proximityScore(plan, reference, originalIndex) {
  const scheduledAt = Date.parse(plan.scheduled_at || "");
  if (Number.isFinite(scheduledAt)) {
    return [0, Math.abs(scheduledAt - reference.getTime()), originalIndex];
  }

  const minutes = clockMinutes(plan.time);
  if (minutes !== null) {
    const referenceMinutes = reference.getHours() * 60 + reference.getMinutes();
    return [0, Math.abs(minutes - referenceMinutes) * 60_000, originalIndex];
  }

  // Meal-related and unrestricted labels have no reliable clock distance.
  // Preserve the server-defined order until a concrete due time is provided.
  return [1, originalIndex, originalIndex];
}

export function orderMedicationPlans(plans, reference = new Date()) {
  return plans
    .map((plan, index) => ({ plan, score: proximityScore(plan, reference, index) }))
    .sort((left, right) => {
      for (let index = 0; index < left.score.length; index += 1) {
        const difference = left.score[index] - right.score[index];
        if (difference !== 0) return difference;
      }
      return 0;
    })
    .map(({ plan }) => plan);
}

function chronologicalTaskScore(plan, reference, originalIndex) {
  const completed = isMedicationPlanCompleted(plan) || plan.status === "已跳过";
  const dateKey = planDateKey(plan) || localDateKey(reference);
  const minutes = clockMinutes(plan.time);
  const timestamp = minutes === null
    ? Number.MAX_SAFE_INTEGER
    : Date.parse(`${dateKey}T${plan.time}:00`);
  return [completed ? 1 : 0, Number.isFinite(timestamp) ? timestamp : Number.MAX_SAFE_INTEGER, originalIndex];
}

export function orderMedicationTaskPickerPlans(plans, reference = new Date()) {
  return plans
    .map((plan, index) => ({ plan, score: chronologicalTaskScore(plan, reference, index) }))
    .sort((left, right) => {
      for (let index = 0; index < left.score.length; index += 1) {
        const difference = left.score[index] - right.score[index];
        if (difference !== 0) return difference;
      }
      return 0;
    })
    .map(({ plan }) => plan);
}
