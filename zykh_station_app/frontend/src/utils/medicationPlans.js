function clockMinutes(value) {
  const match = String(value || "").match(/^([01]\d|2[0-3]):([0-5]\d)$/);
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}

export function medicationPlanTimeLabel(plan) {
  return plan.time || plan.timing_label || plan.schedule_label || "不限时";
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
