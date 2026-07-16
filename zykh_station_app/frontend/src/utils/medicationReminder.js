export function getMedicationReminder(medication, now = new Date(), leadMinutes = 15, overdueMinutes = 60) {
  const candidates = (medication?.plans || [])
    .filter((plan) => plan.status === "待执行" && /^\d{2}:\d{2}$/.test(plan.time || ""))
    .map((plan) => {
      const [hours, minutes] = plan.time.split(":").map(Number);
      const scheduled = new Date(now);
      scheduled.setHours(hours, minutes, 0, 0);
      return { plan, minutesUntil: Math.round((scheduled.getTime() - now.getTime()) / 60000) };
    })
    .filter(({ minutesUntil }) => minutesUntil <= leadMinutes && minutesUntil >= -overdueMinutes)
    .sort((left, right) => Math.abs(left.minutesUntil) - Math.abs(right.minutesUntil));

  if (!candidates.length) return null;
  const reminder = candidates[0];
  return {
    ...reminder,
    state: reminder.minutesUntil > 0 ? "soon" : reminder.minutesUntil < 0 ? "overdue" : "now"
  };
}
